//! Bounded saved component/name and reference/{refname,path} text convention.
//! Reader-generated filename/config roots and selectable configurations are not
//! inferred from this stored hierarchy. Geometry placement remains independent.
use crate::*;
use std::collections::{HashMap, HashSet};

const PROFILE: &str = "edrawings_component_text_v1";
const MAX_COMPONENTS: u64 = 10_000;
const MAX_DEPTH: usize = 256;

fn numbered(name: Option<&str>, prefix: &str) -> bool {
    name.and_then(|s| s.strip_prefix(prefix))
        .is_some_and(|s| !s.is_empty() && s.bytes().all(|c| c.is_ascii_digit()))
}
fn component(n: &SceneNode) -> bool {
    numbered(n.name.as_deref(), "subassem") || numbered(n.name.as_deref(), "assempart")
}
fn unavailable(reason: &str) -> ComponentInventory {
    ComponentInventory {
        profile: PROFILE.into(),
        status: Status::Unsupported,
        reason: Some(reason.into()),
        components: vec![],
    }
}
fn field(p: &PrimitiveInfo) -> ComponentText {
    ComponentText {
        primitive_id: p.id.clone(),
        text: p.text.clone().expect("validated text"),
    }
}

pub(crate) fn inventory(
    scene: &SceneResult,
    budget: &mut hsf_core::Budget,
) -> Result<ComponentInventory, Error> {
    let s = scene.summary();
    budget.charge_output(1024)?;
    if s.hsf.header.version != "19.10"
        || !s.opaque_user_data.iter().any(|u| {
            u.profile
                .starts_with("edrawings-first-be-v2-hsf-19.10-revision-")
        })
    {
        return Ok(unavailable("drawing.component_profile_unavailable"));
    }
    if !s.hsf.unparsed.is_empty()
        || s.processed_records != s.hsf.records.len() as u64
        || s.import_context.is_some()
    {
        return Ok(unavailable("drawing.component_inventory_incomplete"));
    }
    let count = s.nodes.iter().filter(|n| component(n)).count();
    if count == 0 {
        return Ok(unavailable("drawing.component_structure_absent"));
    }
    crate::limits::bound(count as u64, MAX_COMPONENTS, "limits.document_components")?;
    // Account for indexes and their growth before allocation. The input scene
    // already enforces node/text limits; the output has additional fixed caps.
    budget.charge_output((s.nodes.len() as u64 + s.primitives.len() as u64) * 128)?;
    let nodes: HashMap<&str, &SceneNode> = s.nodes.iter().map(|n| (n.id.as_str(), n)).collect();
    let candidates: HashMap<&str, &SceneNode> = s
        .nodes
        .iter()
        .filter(|n| component(n))
        .map(|n| (n.id.as_str(), n))
        .collect();
    budget.charge_output(candidates.len() as u64 * 4096)?;
    let mut parts = HashMap::new();
    for node in &s.nodes {
        if node.name.as_deref() == Some("part")
            && let Some(parent) = node
                .parent_id
                .as_deref()
                .filter(|id| candidates.contains_key(id))
            && parts.insert(parent, node).is_some()
        {
            return Ok(unavailable("drawing.component_part_ambiguous"));
        }
    }
    // Scene matrices describe the final local value. The bounded component
    // convention accepts one literal part opening and one matrix record only;
    // reopened/overwritten definitions are not silently promoted to this API.
    let mut origins = HashMap::new();
    for node in candidates.values().copied().chain(parts.values().copied()) {
        if let Some(source) = &node.source {
            origins.insert((source.domain_id.as_str(), source.offset), node.id.as_str());
        }
    }
    let mut openings = HashMap::new();
    for record in &s.hsf.records {
        if record.kind == "open_segment"
            && let Some(node_id) =
                origins.get(&(record.source.domain_id.as_str(), record.source.offset))
        {
            openings.insert(*node_id, record);
        }
    }
    let component_openings: HashSet<&str> = candidates
        .keys()
        .filter_map(|id| openings.get(id).map(|r| r.id.as_str()))
        .collect();
    let part_openings: HashSet<&str> = parts
        .values()
        .filter_map(|node| openings.get(node.id.as_str()).map(|r| r.id.as_str()))
        .collect();
    let mut part_open_counts: HashMap<&str, usize> = HashMap::new();
    let mut matrix_records: HashMap<&str, (usize, &HsfRecord)> = HashMap::new();
    for record in &s.hsf.records {
        if let Some(scope) = record.scope.as_deref() {
            if record.kind == "open_segment"
                && component_openings.contains(scope)
                && let Some(payload) = record.payload.as_ref().filter(|p| p.length == 4)
                && scene.source_bytes(payload)? == b"part"
            {
                *part_open_counts.entry(scope).or_default() += 1;
            }
            if record.kind == "modelling_matrix" && part_openings.contains(scope) {
                let entry = matrix_records.entry(scope).or_insert((0, record));
                entry.0 += 1;
            }
        }
    }
    let mut transforms = HashMap::new();
    for (component_id, part) in &parts {
        let Some(component_open) = openings.get(component_id) else {
            return Ok(unavailable("drawing.component_part_ambiguous"));
        };
        let Some(part_open) = openings.get(part.id.as_str()) else {
            return Ok(unavailable("drawing.component_part_ambiguous"));
        };
        if part_open.scope.as_deref() != Some(component_open.id.as_str())
            || part_open_counts.get(component_open.id.as_str()) != Some(&1)
        {
            return Ok(unavailable("drawing.component_part_ambiguous"));
        }
        if let Some(matrix) = &part.local_transform {
            let records = matrix_records.get(part_open.id.as_str());
            if records.is_none_or(|(count, r)| *count != 1 || r.source != matrix.source)
                || matrix.value.iter().any(|v| !v.is_finite())
            {
                return Ok(unavailable("drawing.component_part_matrix_ambiguous"));
            }
            transforms.insert(
                *component_id,
                StoredPartTransform {
                    part_node_id: part.id.clone(),
                    matrix: matrix.clone(),
                },
            );
        }
    }
    let mut fields: HashMap<&str, [Option<&PrimitiveInfo>; 3]> = HashMap::new();
    for p in &s.primitives {
        let Some(owner) = nodes.get(p.owner_node_id.as_str()) else {
            return Ok(unavailable("drawing.component_owner_missing"));
        };
        let parent = owner.parent_id.as_deref().and_then(|id| nodes.get(id));
        let (subject, key) = match (owner.name.as_deref(), parent) {
            (Some("name"), Some(parent)) => (parent.id.as_str(), 0),
            (Some("refname" | "path"), Some(parent))
                if parent.name.as_deref() == Some("reference") =>
            {
                let Some(subject) = parent.parent_id.as_deref() else {
                    continue;
                };
                (
                    subject,
                    if owner.name.as_deref() == Some("refname") {
                        1
                    } else {
                        2
                    },
                )
            }
            _ => continue,
        };
        if !candidates.contains_key(subject) {
            continue;
        }
        // Unexpected geometry in a metadata leaf is not silently ignored.
        if !p
            .text
            .as_ref()
            .is_some_and(|t| t.status == Status::Complete && t.value.is_some())
        {
            return Ok(unavailable("drawing.component_text_unavailable"));
        }
        let slot = &mut fields.entry(subject).or_insert([None; 3])[key];
        if slot.replace(p).is_some() {
            return Ok(unavailable("drawing.component_field_ambiguous"));
        }
    }
    if candidates
        .keys()
        .any(|id| fields.get(id).is_none_or(|v| v.iter().any(Option::is_none)))
    {
        return Ok(unavailable("drawing.component_fields_missing"));
    }
    let name = |id: &str| {
        fields[id][0]
            .unwrap()
            .text
            .as_ref()
            .unwrap()
            .value
            .as_deref()
            .unwrap()
    };
    if candidates.keys().any(|id| {
        let value = name(id);
        value.is_empty() || value.contains('/') || value.chars().any(char::is_control)
    }) {
        return Ok(unavailable("drawing.component_name_ambiguous"));
    }
    let mut seen = HashSet::new();
    let mut result = Vec::with_capacity(candidates.len());
    // Source node order, not the Reader's presentation/sorting order.
    for n in s.nodes.iter().filter(|n| component(n)) {
        let mut chain = vec![];
        let mut current = n.id.as_str();
        while let Some(node) = candidates.get(current) {
            crate::limits::bound(
                chain.len() as u64 + 1,
                MAX_DEPTH as u64,
                "limits.component_depth",
            )?;
            if chain.contains(&current) {
                return Ok(unavailable("drawing.component_cycle"));
            }
            chain.push(current);
            let Some(parent) = node.parent_id.as_deref() else {
                return Ok(unavailable("drawing.component_parent_missing"));
            };
            current = parent;
        }
        let mut root = nodes.get(current).copied();
        for expected in ["includes", "3dmodel"] {
            let Some(n) = root.filter(|n| n.name.as_deref() == Some(expected)) else {
                return Ok(unavailable("drawing.component_root_unverified"));
            };
            root = n.parent_id.as_deref().and_then(|id| nodes.get(id).copied());
        }
        for prefix in ["view", "sheet", "config"] {
            let Some(n) = root.filter(|n| numbered(n.name.as_deref(), prefix)) else {
                return Ok(unavailable("drawing.component_root_unverified"));
            };
            root = n.parent_id.as_deref().and_then(|id| nodes.get(id).copied());
        }
        if root.is_none_or(|n| n.parent_id.is_some()) {
            return Ok(unavailable("drawing.component_root_unverified"));
        }
        let values = fields[n.id.as_str()];
        let path_bytes = chain
            .iter()
            .map(|id| name(id).len() as u64 + 1)
            .sum::<u64>();
        crate::limits::bound(path_bytes, 1 << 20, "limits.component_path_bytes")?;
        let text_bytes = values
            .iter()
            .flatten()
            .map(|p| p.text.as_ref().unwrap().value.as_ref().unwrap().len() as u64)
            .sum::<u64>();
        budget.charge_output(4096 + 2 * path_bytes + text_bytes)?;
        let path = chain
            .iter()
            .rev()
            .map(|id| name(id))
            .collect::<Vec<_>>()
            .join("/");
        if !seen.insert((current, path.clone())) {
            return Ok(unavailable("drawing.component_path_ambiguous"));
        }
        result.push(StoredComponent {
            node_id: n.id.clone(),
            parent_component_node_id: n
                .parent_id
                .as_ref()
                .filter(|id| candidates.contains_key(id.as_str()))
                .cloned(),
            root_node_id: current.into(),
            relative_path: path,
            name: field(values[0].unwrap()),
            reference_name: field(values[1].unwrap()),
            reference_path: field(values[2].unwrap()),
            part_transform: transforms.remove(n.id.as_str()),
        });
    }
    Ok(ComponentInventory {
        profile: PROFILE.into(),
        status: Status::Complete,
        reason: None,
        components: result,
    })
}
