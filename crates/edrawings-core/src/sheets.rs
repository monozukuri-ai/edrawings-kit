//! Source-backed root sheetN / viewN,borderviewN inventory. No native index,
//! active state, paper size, unit conversion or projection is inferred.
use crate::*;
use std::collections::{HashMap, HashSet};

const PROFILE: &str = "edrawings_root_sheet_view_v1";
const MAX_SHEETS: u64 = 10_000;
const MAX_VIEWS: u64 = 10_000;

fn numbered(name: &str, prefix: &str) -> bool {
    name.strip_prefix(prefix).is_some_and(|s| {
        !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit()) && (s == "0" || !s.starts_with('0'))
    })
}
fn view_kind(name: &str) -> Option<StoredDrawingViewKind> {
    if numbered(name, "view") {
        Some(StoredDrawingViewKind::View)
    } else if numbered(name, "borderview") {
        Some(StoredDrawingViewKind::BorderView)
    } else {
        None
    }
}
fn candidate(n: &SceneNode) -> bool {
    n.name
        .as_deref()
        .is_some_and(|name| numbered(name, "sheet") || view_kind(name).is_some())
}
fn unavailable(reason: &str) -> SheetInventory {
    SheetInventory {
        profile: PROFILE.into(),
        status: Status::Unsupported,
        reason: Some(reason.into()),
        sheets: vec![],
        views: vec![],
    }
}

pub(crate) fn inventory(
    s: &SceneSummary,
    records: &[UserOptionRecord],
    budget: &mut hsf_core::Budget,
) -> Result<SheetInventory, Error> {
    budget.charge_output(1024)?;
    if !matches!(s.hsf.header.version.as_str(), "8.05" | "19.10")
        || !s
            .opaque_user_data
            .iter()
            .any(|u| match s.hsf.header.version.as_str() {
                "8.05" => u.profile == "edrawings-first-be-v2-hsf-8.05-revision-22",
                "19.10" => u
                    .profile
                    .starts_with("edrawings-first-be-v2-hsf-19.10-revision-"),
                _ => false,
            })
    {
        return Ok(unavailable("drawing.sheet_profile_unavailable"));
    }
    if !s.hsf.unparsed.is_empty()
        || s.processed_records != s.hsf.records.len() as u64
        || s.import_context.is_some()
    {
        return Ok(unavailable("drawing.sheet_inventory_incomplete"));
    }
    let Some(root) = s
        .nodes
        .first()
        .filter(|n| n.parent_id.is_none() && n.name.as_deref() == Some("/") && !n.implicit)
    else {
        return Ok(unavailable("drawing.sheet_structure_unverified"));
    };
    if s.nodes.iter().any(|n| {
        n.parent_id.as_deref() == Some(root.id.as_str())
            && n.name.as_deref().is_some_and(|v| v.starts_with("config"))
    }) {
        // EASM/EPRT also have config/sheet/view groups; they are not promoted
        // to drawing sheets even when every metadata field exists.
        return Ok(unavailable("drawing.sheet_structure_unverified"));
    }
    let sheet_count = s
        .nodes
        .iter()
        .filter(|n| n.name.as_deref().is_some_and(|v| numbered(v, "sheet")))
        .count();
    if sheet_count == 0 {
        return Ok(unavailable("drawing.sheet_structure_absent"));
    }
    crate::limits::bound(sheet_count as u64, MAX_SHEETS, "limits.document_sheets")?;
    let view_count = s
        .nodes
        .iter()
        .filter(|n| n.name.as_deref().and_then(view_kind).is_some())
        .count();
    crate::limits::bound(view_count as u64, MAX_VIEWS, "limits.document_views")?;
    // Indexes borrow scene strings. Charge capacity/growth before allocation.
    budget.charge_output(s.nodes.len() as u64 * 512 + (sheet_count + view_count) as u64 * 1024)?;
    let candidates: HashSet<&str> = s
        .nodes
        .iter()
        .filter(|n| candidate(n))
        .map(|n| n.id.as_str())
        .collect();
    let mut names = HashMap::new();
    // parse_records retains one record per raw User Options in the same order.
    for (record, raw) in records.iter().zip(&s.user_options) {
        if !candidates.contains(record.node_id.as_str()) {
            continue;
        }
        if record.parsing_status != Status::Complete {
            return Ok(unavailable("drawing.sheet_name_unavailable"));
        }
        for a in record.assignments.iter().filter(|a| a.name == "name") {
            if a.value_kind != "explicit"
                || a.value.is_empty()
                || a.value.chars().any(char::is_control)
                || a.value_source.is_none()
            {
                return Ok(unavailable("drawing.sheet_name_unavailable"));
            }
            if names.insert(record.node_id.as_str(), (a, raw)).is_some() {
                return Ok(unavailable("drawing.sheet_name_ambiguous"));
            }
        }
    }
    if candidates.iter().any(|id| !names.contains_key(id)) {
        return Ok(unavailable("drawing.sheet_name_unavailable"));
    }
    let mut sheets: Vec<StoredSheet> = Vec::with_capacity(sheet_count);
    let mut views: Vec<StoredDrawingView> = Vec::with_capacity(view_count);
    // Source nodes are created after their parent. Resolve ancestry once, not
    // by walking every geometry path or following includes/style references.
    let mut membership: HashMap<&str, (Option<usize>, Option<usize>)> = HashMap::new();
    membership.insert(root.id.as_str(), (None, None));
    for n in s.nodes.iter().skip(1) {
        let Some(parent) = n.parent_id.as_deref() else {
            return Ok(unavailable("drawing.sheet_structure_unverified"));
        };
        let Some(&(mut sheet, mut view)) = membership.get(parent) else {
            return Ok(unavailable("drawing.sheet_structure_unverified"));
        };
        let segment = n.name.as_deref().unwrap_or("");
        let is_sheet = numbered(segment, "sheet");
        let kind = view_kind(segment);
        if (parent == root.id && segment.starts_with("sheet") && !is_sheet)
            || (sheet.is_some_and(|i| sheets[i].node_id == parent)
                && (segment.starts_with("view") || segment.starts_with("borderview"))
                && kind.is_none())
        {
            return Ok(unavailable("drawing.sheet_structure_unverified"));
        }
        if is_sheet || kind.is_some() {
            let Some(source) = n.name_source.as_ref().filter(|_| !n.implicit) else {
                return Ok(unavailable("drawing.sheet_source_unavailable"));
            };
            let (a, raw) = names[n.id.as_str()];
            let name_source = a.value_source.as_ref().expect("checked explicit name");
            budget.charge_output(
                4096 + (n.id.len() * 3
                    + parent.len()
                    + segment.len()
                    + a.value.len()
                    + raw.text.encoding.len()
                    + raw.source_record_id.len()
                    + source.domain_id.len()
                    + name_source.domain_id.len()) as u64,
            )?;
            let name = StoredDrawingName {
                value: a.value.clone(),
                encoding: raw.text.encoding.clone(),
                source: name_source.clone(),
                source_record_id: raw.source_record_id.clone(),
            };
            if is_sheet {
                if parent != root.id {
                    return Ok(unavailable("drawing.sheet_structure_unverified"));
                }
                sheet = Some(sheets.len());
                view = None;
                sheets.push(StoredSheet {
                    node_id: n.id.clone(),
                    segment_name: segment.into(),
                    segment_name_source: source.clone(),
                    name,
                    view_node_ids: vec![],
                    primitive_ids: vec![],
                    mesh_ids: vec![],
                });
            } else {
                let Some(i) = sheet.filter(|i| sheets[*i].node_id == parent) else {
                    return Ok(unavailable("drawing.sheet_structure_unverified"));
                };
                view = Some(views.len());
                sheets[i].view_node_ids.push(n.id.clone());
                views.push(StoredDrawingView {
                    node_id: n.id.clone(),
                    sheet_node_id: parent.into(),
                    segment_name: segment.into(),
                    segment_name_source: source.clone(),
                    kind: kind.expect("checked view kind"),
                    name,
                    model_2d_node_id: None,
                    model_3d_node_id: None,
                    primitive_ids: vec![],
                    mesh_ids: vec![],
                });
            }
        } else if let Some(i) = view.filter(|i| views[*i].node_id == parent) {
            let slot = match segment {
                "2dmodel" => Some(&mut views[i].model_2d_node_id),
                "3dmodel" => Some(&mut views[i].model_3d_node_id),
                _ => None,
            };
            if let Some(slot) = slot {
                if n.implicit || n.name_source.is_none() || slot.is_some() {
                    return Ok(unavailable("drawing.sheet_structure_unverified"));
                }
                budget.charge_output(128 + n.id.len() as u64)?;
                *slot = Some(n.id.clone());
            }
        }
        if membership.insert(n.id.as_str(), (sheet, view)).is_some() {
            return Ok(unavailable("drawing.sheet_structure_unverified"));
        }
    }
    if sheets.iter().any(|s| s.view_node_ids.is_empty())
        || views
            .iter()
            .any(|v| v.model_2d_node_id.is_none() && v.model_3d_node_id.is_none())
    {
        return Ok(unavailable("drawing.sheet_structure_unverified"));
    }
    for (id, owner, mesh) in s
        .primitives
        .iter()
        .map(|p| (&p.id, &p.owner_node_id, false))
        .chain(s.meshes.iter().map(|m| (&m.id, &m.owner_node_id, true)))
    {
        let Some(&(sheet, view)) = membership.get(owner.as_str()) else {
            return Ok(unavailable("drawing.sheet_geometry_owner_missing"));
        };
        if let Some(i) = sheet {
            budget.charge_output(128 + id.len() as u64)?;
            if mesh {
                sheets[i].mesh_ids.push(id.clone());
            } else {
                sheets[i].primitive_ids.push(id.clone());
            }
        }
        if let Some(i) = view {
            budget.charge_output(128 + id.len() as u64)?;
            if mesh {
                views[i].mesh_ids.push(id.clone());
            } else {
                views[i].primitive_ids.push(id.clone());
            }
        }
    }
    Ok(SheetInventory {
        profile: PROFILE.into(),
        status: Status::Complete,
        reason: None,
        sheets,
        views,
    })
}
