//! Observed DXF Reader 34.4 drawing-plane units, without global XYZ semantics.
use crate::*;
use std::collections::HashMap;

const PROFILE: &str = "edrawings_dxf_34_4_xy_v1";
const HEADER: &str = "edrawings-first-be-v2-hsf-19.10-revision-51";
const WRITER: &[u8] = b"DXF/DWG Reader AddIn (34.4.1.0003)";

fn unavailable(reason: &str) -> DrawingPlaneProfile {
    DrawingPlaneProfile {
        profile: PROFILE.into(),
        status: Status::Unsupported,
        reason: Some(reason.into()),
        root_length: None,
        header_unit: None,
        source_length_unit: None,
        stored_xy_unit: None,
        xy_meters_per_saved_unit: None,
        source_units_to_meters: None,
        z_semantics: "uninterpreted_drawing_depth".into(),
        cad_origin: "unavailable".into(),
    }
}
fn reject(mut out: DrawingPlaneProfile, reason: &str) -> DrawingPlaneProfile {
    out.reason = Some(reason.into());
    out
}
fn field<'a>(u: &'a UserDataLayout, label: &str) -> Option<&'a HsfSpan> {
    let mut matches = u.fields.iter().filter(|f| f.label == label);
    let first = matches.next()?;
    matches.next().is_none().then_some(&first.source)
}

pub(crate) fn profile(
    scene: &SceneResult,
    records: &[UserOptionRecord],
    sheets: &SheetInventory,
    budget: &mut hsf_core::Budget,
) -> Result<DrawingPlaneProfile, Error> {
    budget.charge_output(4096)?;
    let s = scene.summary();
    let mut out = unavailable("drawing.plane_profile_unavailable");
    if s.hsf.header.version != "19.10" {
        return Ok(out);
    }
    // Whole record/domain coverage is required. The conservative scene and
    // placement statuses deliberately remain partial/unsupported.
    if !s.hsf.unparsed.is_empty()
        || s.processed_records != s.hsf.records.len() as u64
        || s.hsf.domains.iter().any(|d| d.parsed_bytes != d.byte_len)
        || s.import_context.is_some()
    {
        return Ok(reject(out, "drawing.plane_incomplete"));
    }
    let mut headers = s
        .hsf
        .records
        .iter()
        .filter(|r| r.user_data.as_ref().is_some_and(|u| u.profile == HEADER));
    let Some(header) = headers.next() else {
        return Ok(out);
    };
    if headers.next().is_some() {
        return Ok(reject(out, "drawing.plane_header_ambiguous"));
    }
    let u = header.user_data.as_ref().expect("filtered header");
    let Some(words) = field(u, "opaque_words").filter(|p| p.length == 16) else {
        return Ok(reject(out, "drawing.plane_header_unavailable"));
    };
    let raw_words = scene.source_bytes(words)?;
    let code = u32::from_le_bytes(raw_words[12..16].try_into().expect("four bytes"));
    budget.charge_output((words.domain_id.len() + header.id.len()) as u64)?;
    out.header_unit = Some(DrawingHeaderUnit {
        raw_value: code,
        source: HsfSpan {
            domain_id: words.domain_id.clone(),
            offset: words.offset + 12,
            length: 4,
        },
        source_record_id: header.id.clone(),
    });
    let Some(root) = s
        .nodes
        .first()
        .filter(|n| n.parent_id.is_none() && n.name.as_deref() == Some("/") && !n.implicit)
    else {
        return Ok(reject(out, "drawing.plane_root_unavailable"));
    };
    let mut length = None;
    for record in records.iter().filter(|r| r.node_id == root.id) {
        if record.parsing_status != Status::Complete {
            return Ok(reject(out, "drawing.plane_length_unavailable"));
        }
        for assignment in record.assignments.iter().filter(|a| a.name == "length") {
            if length.is_some() {
                return Ok(reject(out, "drawing.plane_length_ambiguous"));
            }
            if assignment.value_kind != "explicit" || assignment.value_source.is_none() {
                return Ok(reject(out, "drawing.plane_length_unavailable"));
            }
            length = Some((assignment, record));
        }
    }
    let Some((length, record)) = length else {
        return Ok(reject(out, "drawing.plane_length_unavailable"));
    };
    let source = length.value_source.as_ref().expect("explicit source");
    budget.charge_output(
        (length.value.len() + source.domain_id.len() + record.source_record_id.len()) as u64,
    )?;
    out.root_length = Some(DrawingLengthOption {
        raw_value: length.value.clone(),
        source: source.clone(),
        source_record_id: record.source_record_id.clone(),
    });
    let Some(writer) = field(u, "leading_string_1") else {
        return Ok(out);
    };
    if scene.source_bytes(writer)? != WRITER {
        return Ok(reject(out, "drawing.plane_writer_unverified"));
    }
    let Some(matrix) = field(u, "matrix_candidate").filter(|p| p.length == 64) else {
        return Ok(out);
    };
    let raw_matrix = scene.source_bytes(matrix)?;
    if raw_matrix.chunks_exact(4).enumerate().any(|(i, b)| {
        u32::from_le_bytes(b.try_into().expect("four bytes"))
            != if i % 5 == 0 { 1f32.to_bits() } else { 0 }
    }) || raw_words[..12] != [0, 0, 0, 0, 2, 0, 0, 0, 4, 0, 0, 0]
    {
        return Ok(reject(out, "drawing.plane_header_unverified"));
    }
    let (unit, scale) = match (length.value.as_str(), code) {
        ("3", 0) => (DrawingLengthUnit::Millimeter, 0.001),
        ("4", 1) => (DrawingLengthUnit::Centimeter, 0.01),
        ("5", 2) => (DrawingLengthUnit::Meter, 1.0),
        ("8", 3) => (DrawingLengthUnit::Inch, 0.0254),
        _ => return Ok(reject(out, "drawing.plane_unit_pair_unverified")),
    };
    if sheets.status != Status::Complete
        || !s.meshes.is_empty()
        || s.primitives.is_empty()
        || sheets
            .sheets
            .iter()
            .map(|sh| sh.primitive_ids.len())
            .sum::<usize>()
            != s.primitives.len()
    {
        return Ok(reject(out, "drawing.plane_geometry_unverified"));
    }
    budget.charge_output(s.nodes.len() as u64 * 128)?;
    let mut transformed: HashMap<&str, bool> = HashMap::with_capacity(s.nodes.len());
    for n in &s.nodes {
        let parent = match n.parent_id.as_deref() {
            Some(p) => match transformed.get(p) {
                Some(v) => *v,
                None => return Ok(reject(out, "drawing.plane_ancestry_unverified")),
            },
            None => false,
        };
        transformed.insert(n.id.as_str(), parent || n.local_transform.is_some());
    }
    if s.primitives
        .iter()
        .any(|p| transformed.get(p.owner_node_id.as_str()) != Some(&false))
    {
        return Ok(reject(out, "drawing.plane_transform_unverified"));
    }
    out.status = Status::Complete;
    out.reason = None;
    out.source_length_unit = Some(unit);
    out.stored_xy_unit = Some(DrawingLengthUnit::Meter);
    out.xy_meters_per_saved_unit = Some(1.0);
    out.source_units_to_meters = Some(scale);
    Ok(out)
}
