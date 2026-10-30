//! Multiple saved configN groups with explicit `config name` User Options.
//! Source order and ownership are retained. The active configuration is the one
//! group the writer left visible (every other `configN` segment carries a face
//! visibility off record); without that marker none is claimed.
use crate::*;
use std::collections::{HashMap, HashSet};
const PROFILE: &str = "edrawings_multi_config_options_v1";
fn numbered(name: Option<&str>, prefix: &str) -> bool {
    name.and_then(|s| s.strip_prefix(prefix)).is_some_and(|s| {
        !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()) && (s == "0" || !s.starts_with('0'))
    })
}
fn unavailable(reason: &str) -> ConfigurationInventory {
    ConfigurationInventory {
        profile: PROFILE.into(),
        status: Status::Unsupported,
        reason: Some(reason.into()),
        configurations: vec![],
        active_configuration_node_id: None,
    }
}
pub(crate) fn inventory(
    s: &SceneSummary,
    records: &[UserOptionRecord],
    budget: &mut hsf_core::Budget,
) -> Result<ConfigurationInventory, Error> {
    budget.charge_output(1024)?;
    if s.hsf.header.version != "19.10"
        || !s.opaque_user_data.iter().any(|u| {
            u.profile
                .starts_with("edrawings-first-be-v2-hsf-19.10-revision-")
        })
    {
        return Ok(unavailable("drawing.configuration_profile_unavailable"));
    }
    if !s.hsf.unparsed.is_empty() || s.processed_records != s.hsf.records.len() as u64 {
        return Ok(unavailable("drawing.configuration_inventory_incomplete"));
    }
    let root = s
        .import_context
        .as_ref()
        .map(|c| c.node_id.as_str())
        .or_else(|| {
            s.nodes
                .first()
                .filter(|n| n.parent_id.is_none())
                .map(|n| n.id.as_str())
        });
    let Some(root) = root else {
        return Ok(unavailable("drawing.configuration_structure_unverified"));
    };
    let count = s
        .nodes
        .iter()
        .filter(|n| numbered(n.name.as_deref(), "config"))
        .count();
    // A single saved Default is not evidence of a public selectable configuration.
    if count < 2 {
        return Ok(unavailable("drawing.multiple_configurations_absent"));
    }
    crate::limits::bound(count as u64, 10_000, "limits.document_configurations")?;
    budget.charge_output(s.nodes.len() as u64 * 256 + count as u64 * 4096)?;
    let nodes: HashMap<&str, &SceneNode> = s.nodes.iter().map(|n| (n.id.as_str(), n)).collect();
    let candidates: HashSet<&str> = s
        .nodes
        .iter()
        .filter(|n| numbered(n.name.as_deref(), "config"))
        .map(|n| n.id.as_str())
        .collect();
    let mut names = HashMap::new();
    for (record, raw) in records.iter().zip(&s.user_options) {
        if !candidates.contains(record.node_id.as_str()) {
            continue;
        }
        if record.parsing_status != Status::Complete {
            return Ok(unavailable("drawing.configuration_name_unavailable"));
        }
        for a in record
            .assignments
            .iter()
            .filter(|a| a.name == "config name")
        {
            if a.value_kind != "explicit"
                || a.value.is_empty()
                || a.value.chars().any(char::is_control)
                || a.value_source.is_none()
            {
                return Ok(unavailable("drawing.configuration_name_unavailable"));
            }
            if names.insert(record.node_id.as_str(), (a, raw)).is_some() {
                return Ok(unavailable("drawing.configuration_name_ambiguous"));
            }
        }
    }
    let mut result: Vec<StoredConfiguration> = vec![];
    let mut membership: HashMap<&str, Option<usize>> = HashMap::new();
    let mut labels = HashSet::new();
    let mut numbers = HashSet::new();
    for n in &s.nodes {
        let parent = n.parent_id.as_deref();
        let mut owner = if let Some(parent) = parent {
            let Some(owner) = membership.get(parent) else {
                return Ok(unavailable("drawing.configuration_structure_unverified"));
            };
            *owner
        } else {
            None
        };
        if numbered(n.name.as_deref(), "config") {
            if parent != Some(root) || owner.is_some() || n.implicit {
                return Ok(unavailable("drawing.configuration_structure_unverified"));
            }
            let Some(source) = n.name_source.as_ref() else {
                return Ok(unavailable("drawing.configuration_source_unavailable"));
            };
            let Some((a, raw)) = names.get(n.id.as_str()) else {
                return Ok(unavailable("drawing.configuration_name_unavailable"));
            };
            let segment = n.name.as_ref().unwrap();
            let number = segment[6..].parse::<usize>().ok();
            if number.is_none_or(|v| v >= count)
                || !numbers.insert(number.unwrap())
                || !labels.insert(a.value.as_str())
            {
                return Ok(unavailable("drawing.configuration_name_ambiguous"));
            }
            budget.charge_output(4096 + (n.id.len() + segment.len() + a.value.len()) as u64)?;
            owner = Some(result.len());
            result.push(StoredConfiguration {
                node_id: n.id.clone(),
                segment_name: segment.clone(),
                segment_name_source: source.clone(),
                name: StoredDrawingName {
                    value: a.value.clone(),
                    encoding: raw.text.encoding.clone(),
                    source: a.value_source.clone().unwrap(),
                    source_record_id: raw.source_record_id.clone(),
                },
                component_node_ids: vec![],
            });
        } else if parent == Some(root) && n.name.as_deref().is_some_and(|v| v.starts_with("config"))
        {
            return Ok(unavailable("drawing.configuration_structure_unverified"));
        }
        if (numbered(n.name.as_deref(), "subassem") || numbered(n.name.as_deref(), "assempart"))
            && let Some(i) = owner
        {
            let mut ancestor = parent.and_then(|p| nodes.get(p).copied());
            let mut depth = 0;
            while ancestor.is_some_and(|n| {
                numbered(n.name.as_deref(), "subassem") || numbered(n.name.as_deref(), "assempart")
            }) {
                depth += 1;
                crate::limits::bound(depth, 256, "limits.component_depth")?;
                ancestor = ancestor
                    .and_then(|n| n.parent_id.as_deref())
                    .and_then(|id| nodes.get(id).copied());
            }
            for expected in ["includes", "3dmodel"] {
                let Some(a) = ancestor.filter(|a| a.name.as_deref() == Some(expected)) else {
                    return Ok(unavailable(
                        "drawing.configuration_component_context_unverified",
                    ));
                };
                ancestor = a.parent_id.as_deref().and_then(|id| nodes.get(id).copied());
            }
            for prefix in ["view", "sheet"] {
                let Some(a) = ancestor.filter(|a| numbered(a.name.as_deref(), prefix)) else {
                    return Ok(unavailable(
                        "drawing.configuration_component_context_unverified",
                    ));
                };
                ancestor = a.parent_id.as_deref().and_then(|id| nodes.get(id).copied());
            }
            if ancestor.is_none_or(|a| a.id != result[i].node_id) {
                return Ok(unavailable(
                    "drawing.configuration_component_context_unverified",
                ));
            }
            budget.charge_output(128 + n.id.len() as u64)?;
            result[i].component_node_ids.push(n.id.clone());
        }
        membership.insert(n.id.as_str(), owner);
    }
    let hidden = |c: &StoredConfiguration| {
        nodes
            .get(c.node_id.as_str())
            .and_then(|n| n.face_visible.as_ref())
            .is_some_and(|a| !a.value)
    };
    let active_configuration_node_id = if result.iter().any(hidden) {
        result
            .iter()
            .find(|c| !hidden(c))
            .map(|c| c.node_id.clone())
    } else {
        None
    };
    Ok(ConfigurationInventory {
        profile: PROFILE.into(),
        status: Status::Complete,
        reason: None,
        configurations: result,
        active_configuration_node_id,
    })
}
