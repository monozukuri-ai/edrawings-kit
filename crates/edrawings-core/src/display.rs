//! Display bundles: placed bodies for viewers, built from one bounded scene read.
//!
//! The bundle is an estimate for display, not a verified document model:
//! placements follow the stored segment tree, modelling matrices, includes and
//! repeat instances (`PlacementPolicy::SceneGraphV1`); colours come from the
//! inherited HSF colour, then the container's `materials.xml`, then a component's
//! `defaultcolor` option; one saved configuration is shown at a time.
use crate::hsf_adapter::{diagnostic, status};
use crate::scene_adapter::text_value;
use crate::*;
use quick_xml::{Reader, XmlVersion, events::Event};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;

/// Colour sources for instances.
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ColorPolicy {
    /// Inherited HSF colour, then `materials.xml`, then component `defaultcolor`.
    #[default]
    MaterialsXml,
    /// Inherited HSF colour only.
    HsfOnly,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, deny_unknown_fields)]
pub struct DisplayOptions {
    pub placement: PlacementPolicy,
    pub colors: ColorPolicy,
    /// Saved configuration to show: its `config name` or `configN` segment name.
    /// None selects the file's active configuration (the `configN` segment the
    /// writer left visible), else the first.
    pub configuration: Option<String>,
    /// Display state of the shown configuration to apply: a `dispN` segment name
    /// or the state's `name` option. None applies the configuration's `current`
    /// state, else its `default`.
    pub display_state: Option<String>,
    /// Keep instances that eDrawings hides (default visibility off, or a display
    /// state override) in the buffers with `visibility` 0. Default: drop them.
    pub include_hidden: bool,
    pub profiles: HsfProfiles,
    pub import_root: Option<String>,
}
impl Default for DisplayOptions {
    fn default() -> Self {
        Self {
            placement: PlacementPolicy::SceneGraphV1,
            colors: ColorPolicy::MaterialsXml,
            configuration: None,
            display_state: None,
            include_hidden: false,
            profiles: HsfProfiles {
                user_data: UserDataPolicy::EdrawingsBeEnvelopeV1,
                image: ImagePolicy::Edrawings1910U32V1,
            },
            import_root: None,
        }
    }
}

/// Packed buffers of one body in local coordinates.
#[derive(Clone, Debug, Default)]
pub struct BodyBuffers {
    pub positions: Vec<[f32; 3]>,
    pub normals: Vec<[f32; 3]>,
    pub triangles: Vec<[u32; 3]>,
    pub edges: Vec<[u32; 2]>,
}
/// Packed per-instance arrays; indices refer to `DisplaySummary` tables.
#[derive(Clone, Debug, Default)]
pub struct InstanceBuffers {
    pub matrices: Vec<[f64; 16]>,
    pub bodies: Vec<u32>,
    pub colors: Vec<[u8; 4]>,
    pub color_sources: Vec<u8>,
    /// Inherited HSF face visibility: 0 off, 1 on, 2 unset (the stored flag).
    pub face_visibility: Vec<u8>,
    /// Effective eDrawings visibility: 1 shown, 0 hidden. The stored flag (or a
    /// `defaultvisibility` option) is the default; the active display state's
    /// `path=…,vis=on|off` entries override it. Hidden instances are present
    /// only with `DisplayOptions::include_hidden`.
    pub visibility: Vec<u8>,
    pub names: Vec<u32>,
    pub component_paths: Vec<u32>,
}
#[derive(Clone, Debug)]
pub struct DisplayResult {
    summary: DisplaySummary,
    bodies: Vec<BodyBuffers>,
    instances: InstanceBuffers,
    preview: Option<(Arc<[u8]>, String)>,
}
impl DisplayResult {
    pub fn summary(&self) -> &DisplaySummary {
        &self.summary
    }
    pub fn body(&self, index: usize) -> Result<&BodyBuffers, Error> {
        self.bodies
            .get(index)
            .ok_or_else(|| Error::invalid("display.unknown_body", "display", "Unknown body index"))
    }
    pub fn instances(&self) -> &InstanceBuffers {
        &self.instances
    }
    pub fn preview(&self) -> Option<(&[u8], &str)> {
        self.preview.as_ref().map(|(d, m)| (d.as_ref(), m.as_str()))
    }
}

struct Material {
    rgb: [u8; 3],
    alpha: u8,
}

fn numbered(name: Option<&str>, prefix: &str) -> bool {
    name.and_then(|s| s.strip_prefix(prefix)).is_some_and(|s| {
        !s.is_empty() && s.bytes().all(|b| b.is_ascii_digit()) && (s == "0" || !s.starts_with('0'))
    })
}
fn number(name: &str, prefix: &str) -> u64 {
    name.strip_prefix(prefix)
        .and_then(|s| s.parse().ok())
        .unwrap_or(u64::MAX)
}
/// Last literal component of a stored segment name, lower-cased with spaces
/// collapsed, matching the path normalization of the scene builder.
fn component_name(name: &str) -> String {
    let last = name.rsplit('/').next().unwrap_or(name);
    last.split(' ')
        .filter(|s| !s.is_empty())
        .collect::<Vec<_>>()
        .join(" ")
        .to_ascii_lowercase()
}

fn info(entry: &str, code: &str, message: String) -> Diagnostic {
    let mut d = Diagnostic::new(code, Status::Partial, "display", &message).entry(entry);
    d.severity = "info".into();
    d
}
fn warning(entry: &str, code: &str, message: String) -> Diagnostic {
    let mut d = Diagnostic::new(code, Status::Partial, "display", &message).entry(entry);
    d.severity = "warning".into();
    d
}

/// Face outline edges: triangle edges with one triangle or two different faces.
fn outline_edges(triangles: &[[u32; 3]], faces: &[u32]) -> Vec<[u32; 2]> {
    let mut map: HashMap<(u32, u32), (u32, u8, bool)> = HashMap::with_capacity(triangles.len() * 3);
    for (t, tri) in triangles.iter().enumerate() {
        let face = faces.get(t).copied().unwrap_or(t as u32);
        for k in 0..3 {
            let (a, b) = (tri[k], tri[(k + 1) % 3]);
            let key = if a < b { (a, b) } else { (b, a) };
            match map.get_mut(&key) {
                Some(e) => {
                    e.1 = e.1.saturating_add(1);
                    if e.0 != face {
                        e.2 = true;
                    }
                }
                None => {
                    map.insert(key, (face, 1, false));
                }
            }
        }
    }
    let mut edges: Vec<[u32; 2]> = map
        .into_iter()
        .filter(|(_, (_, count, mixed))| *count == 1 || *mixed)
        .map(|((a, b), _)| [a, b])
        .collect();
    edges.sort_unstable();
    edges
}

fn parse_materials(xml: &[u8], limits: &Limits) -> Result<HashMap<String, Material>, Error> {
    limits::bound(xml.len() as u64, limits.max_xml_bytes, "limits.xml_bytes")?;
    let bad = |m: &str| Error::invalid("materials.invalid", "display", m);
    let mut reader = Reader::from_reader(xml);
    reader.config_mut().enable_all_checks(true);
    reader.config_mut().trim_text(true);
    let mut result = HashMap::new();
    let mut entity: Option<String> = None;
    let mut rgb: Option<[u8; 3]> = None;
    let mut alpha = 255u8;
    let mut elements = 0u64;
    let mut depth = 0u64;
    loop {
        let event = reader.read_event().map_err(|e| bad(&e.to_string()))?;
        match &event {
            Event::Start(e) | Event::Empty(e) => {
                if matches!(event, Event::Start(_)) {
                    depth += 1;
                }
                elements += 1;
                limits::bound(elements, limits.max_xml_elements, "limits.xml_elements")?;
                let name = e.name();
                let attrs = || -> Result<HashMap<String, String>, Error> {
                    let mut out = HashMap::new();
                    for a in e.attributes() {
                        let a = a.map_err(|e| bad(&e.to_string()))?;
                        let key = String::from_utf8_lossy(a.key.as_ref()).into_owned();
                        let value = a
                            .decoded_and_normalized_value(XmlVersion::Implicit1_0, reader.decoder())
                            .map_err(|e| bad(&e.to_string()))?
                            .into_owned();
                        out.insert(key, value);
                    }
                    Ok(out)
                };
                match name.as_ref() {
                    b"Entity" => {
                        entity = attrs()?.remove("name");
                        rgb = None;
                        alpha = 255;
                    }
                    b"MaterialProps" => {
                        if let Some(t) = attrs()?
                            .get("Transparency")
                            .and_then(|v| v.parse::<f32>().ok())
                        {
                            alpha = (255.0 * (1.0 - t.clamp(0.0, 1.0))).round() as u8;
                        }
                    }
                    b"MaterialColor1" => {
                        let a = attrs()?;
                        let channel = |k: &str| a.get(k).and_then(|v| v.parse::<f32>().ok());
                        if let (Some(r), Some(g), Some(b)) =
                            (channel("red"), channel("green"), channel("blue"))
                        {
                            rgb = Some([r, g, b].map(|v| v.clamp(0.0, 255.0).round() as u8));
                        }
                    }
                    _ => {}
                }
                if matches!(event, Event::Empty(_)) && name.as_ref() == b"Entity" {
                    entity = None;
                }
            }
            Event::End(e) => {
                depth = depth
                    .checked_sub(1)
                    .ok_or_else(|| bad("Unmatched end tag"))?;
                if e.name().as_ref() == b"Entity"
                    && let (Some(name), Some(color)) = (entity.take(), rgb.take())
                {
                    result.insert(name.to_ascii_lowercase(), Material { rgb: color, alpha });
                }
            }
            Event::Eof => break,
            _ => {}
        }
    }
    if depth != 0 || elements == 0 {
        return Err(bad("Missing root or incomplete XML element"));
    }
    Ok(result)
}

/// Choose the saved configuration before the scene exists, from root-level
/// `configN` open-segment records and their direct `config name` options, with
/// the same rule as the post-scene selection (explicit name or segment, else the
/// first header's candidate, else the first). `All` when the file saves no
/// configurations, or when an explicit request matches nothing (the scene then
/// reports `display.configuration_unknown` with the candidate list).
fn configuration_subtree(
    doc: &hsf_core::HsfDocument,
    entry: &str,
    options: &DisplayOptions,
    candidate: Option<&str>,
    budget: &mut hsf_core::Budget,
) -> Result<hsf_core::Traversal, Error> {
    let mut configs: Vec<(String, String, u64)> = Vec::new();
    for r in &doc.records {
        if r.opcode != b'(' || r.scope.is_some() {
            continue;
        }
        let Some(bytes) = r.payload.as_ref().and_then(|p| doc.source_bytes(p)) else {
            continue;
        };
        let Ok(name) = std::str::from_utf8(bytes) else {
            continue;
        };
        if numbered(Some(name), "config") {
            budget.charge_output(128)?;
            configs.push((r.id.clone(), name.to_owned(), number(name, "config")));
        }
    }
    if configs.is_empty() {
        return Ok(hsf_core::Traversal::All);
    }
    configs.sort_by_key(|c| c.2);
    // The writer hides every configuration except the active one with a face
    // visibility off record directly on its segment.
    let hidden: std::collections::HashSet<&str> = doc
        .records
        .iter()
        .filter(|r| r.opcode == b'V')
        .filter_map(|r| {
            let scope = r.scope.as_deref()?;
            let v = r.visibility.as_ref()?;
            (v.mask & 1 != 0 && v.value & 1 == 0 && configs.iter().any(|c| c.0 == scope))
                .then_some(scope)
        })
        .collect();
    let failed = |e: hsf_core::HsfError| Error::Format(Box::new(diagnostic(entry, *e.diagnostic)));
    let mut records: Vec<UserOptions> = Vec::new();
    for r in &doc.records {
        let Some(scope) = r.scope.as_deref() else {
            continue;
        };
        if !configs.iter().any(|c| c.0 == scope) {
            continue;
        }
        if let Some(text) = hsf_core::user_option_text(doc, r, budget).map_err(failed)? {
            records.push(UserOptions {
                node_id: scope.to_owned(),
                source_record_id: r.id.clone(),
                text: text_value(entry, text),
            });
        }
    }
    let mut names: HashMap<&str, String> = HashMap::new();
    let parsed = user_options::parse_records(&records, budget)?;
    for record in &parsed {
        for a in &record.assignments {
            if a.name == "config name" && a.value_kind == "explicit" {
                names.insert(record.node_id.as_str(), a.value.clone());
            }
        }
    }
    let _ = candidate;
    let chosen = if let Some(wanted) = &options.configuration {
        configs
            .iter()
            .find(|c| names.get(c.0.as_str()) == Some(wanted) || c.1 == *wanted)
    } else {
        configs
            .iter()
            .find(|c| !hidden.contains(c.0.as_str()))
            .or(configs.first())
    };
    Ok(match chosen {
        Some(c) => hsf_core::Traversal::Subtree(format!("/{}", c.1)),
        None => hsf_core::Traversal::All,
    })
}

pub(crate) fn read(
    doc: &Document,
    extraction: Extraction,
    options: &DisplayOptions,
    budget: &mut hsf_core::Budget,
) -> Result<DisplayResult, Error> {
    let limits = doc.limits();
    let entry = extraction.info.entry_id.clone();
    let hsf_version;
    let records;
    let unparsed_bytes: u64;
    let processed;
    let header_strings;
    let mount_path;
    let scene;
    let user_data_profile;
    let index_names: HashMap<String, String>;
    {
        let parse_options = hsf_adapter::options(HsfMode::Partial, limits, options.profiles.image);
        let failed =
            |e: hsf_core::HsfError| Error::Format(Box::new(diagnostic(&entry, *e.diagnostic)));
        let parsed = hsf_core::parse_precharged_with_user_data(
            Arc::from(extraction.data),
            &parse_options,
            budget,
            options.profiles.user_data.profile(),
        )
        .map_err(failed)?;
        hsf_version = parsed.data.header.version.text.clone();
        records = parsed.data.records.len() as u64;
        unparsed_bytes = parsed.unparsed.iter().map(|u| u.length).sum();
        mount_path = options.profiles.user_data.mount_path(&parsed.data);
        user_data_profile = parsed
            .data
            .records
            .get(3)
            .and_then(|r| r.user_data.as_ref())
            .map(|u| u.profile.clone());
        header_strings = [
            "leading_string_0",
            "leading_string_1",
            "configuration_candidate",
            "revision_string_candidate",
        ]
        .map(|label| user_data::first_header_text(&parsed.data, label));
        // Place one saved configuration only: pick it from the syntax records so
        // the other configN subtrees are never traversed (an eleven-configuration
        // assembly otherwise multiplies its instances eleven times).
        let traversal = configuration_subtree(
            &parsed.data,
            &entry,
            options,
            header_strings[2].as_deref(),
            budget,
        )?;
        let scene_options = hsf_core::SceneOptions {
            mode: hsf_core::ParseMode::Partial,
            import_root: options.import_root.clone(),
            max_meshes: limits.max_scene_meshes,
            max_primitives: limits.max_scene_primitives,
            max_nodes: limits.max_scene_nodes,
            max_instances: limits.max_scene_instances,
            max_depth: limits.max_scene_depth,
            max_visits: limits.max_scene_visits,
            max_triangles: limits.max_scene_triangles,
            max_views: limits.max_scene_views,
            max_definitions: limits.max_scene_definitions,
            inventory_user_data_record: options.profiles.user_data.inventory_record(&parsed.data),
            inventory_terminal_user_data_record: options
                .profiles
                .user_data
                .inventory_terminal_record(&parsed.data),
            mount_path: mount_path.clone(),
            placement: options.placement.backend(),
            traversal,
        };
        scene = hsf_core::scene(&parsed, &scene_options, budget).map_err(failed)?;
        processed = scene.data.processed_records;
        // TKE_User_Index_Data `name` entries: HOOPS Exchange based writers
        // (eDrawings 2026) keep component, body and model names there as
        // NUL-terminated bytes. Decoded leniently; other indices stay opaque.
        let name_index = i32::from_le_bytes(*b"name");
        let mut names_by_node: HashMap<String, String> = HashMap::new();
        for u in &scene.data.user_index_data {
            for e in u.layout.entries.iter().filter(|e| e.index == name_index) {
                let Some(bytes) = parsed.data.source_bytes(&e.data) else {
                    continue;
                };
                let text = String::from_utf8_lossy(bytes)
                    .trim_end_matches('\0')
                    .trim()
                    .to_owned();
                if text.is_empty() || text.chars().any(char::is_control) {
                    continue;
                }
                budget.charge_output(64 + text.len() as u64)?;
                names_by_node.entry(u.node_id.clone()).or_insert(text);
            }
        }
        index_names = names_by_node;
        // Syntax records are no longer needed; only the scene outcome is retained.
    }
    let data = scene.data;
    let mut diagnostics: Vec<Diagnostic> = scene
        .diagnostics
        .into_iter()
        .map(|d| diagnostic(&entry, d))
        .collect();
    let stopped_record_id = (processed < records).then(|| format!("{entry}/record:{processed}"));
    if let Some(id) = &stopped_record_id {
        diagnostics.push(warning(
            &entry,
            "edrawings.display_stopped",
            format!("Scene processing stopped at {id} of {records} records; the bundle covers the processed prefix"),
        ));
    }
    if unparsed_bytes > 0 {
        diagnostics.push(warning(
            &entry,
            "edrawings.display_syntax_stopped",
            format!("{unparsed_bytes} bytes were not parsed after an unsupported record; the bundle covers the parsed prefix only"),
        ));
    }

    // Node index, paths and names.
    let nodes = &data.nodes;
    budget.charge_output(nodes.len() as u64 * 192)?;
    let node_index: HashMap<&str, usize> = nodes
        .iter()
        .enumerate()
        .map(|(i, n)| (n.id.as_str(), i))
        .collect();
    let mut paths: Vec<String> = Vec::with_capacity(nodes.len());
    for n in nodes {
        let parent = n
            .parent_id
            .as_deref()
            .and_then(|p| node_index.get(p).copied());
        let path = match parent {
            None => "/".to_string(),
            Some(p) => {
                let name = component_name(n.name.as_deref().unwrap_or(""));
                if paths[p] == "/" {
                    format!("/{name}")
                } else {
                    format!("{}/{name}", paths[p])
                }
            }
        };
        paths.push(path);
    }
    let root = data
        .import_context
        .as_ref()
        .and_then(|c| node_index.get(c.node_id.as_str()).copied())
        .unwrap_or(0);

    // User options: configuration names, component names and default colours.
    let option_records = user_options::parse_records(
        &data
            .user_options
            .iter()
            .map(|u| UserOptions {
                node_id: u.node_id.clone(),
                source_record_id: u.source_record_id.clone(),
                text: text_value(&entry, u.text.clone()),
            })
            .collect::<Vec<_>>(),
        budget,
    )?;
    let mut config_names: HashMap<&str, String> = HashMap::new();
    let mut option_names: HashMap<&str, String> = HashMap::new();
    let mut default_colors: HashMap<&str, [u8; 4]> = HashMap::new();
    let mut model_units: Option<f64> = None;
    for record in &option_records {
        let mut color: Option<[u8; 3]> = None;
        let mut transmission = 0f32;
        let mut mbd_name: Option<String> = None;
        let mut plain_name: Option<String> = None;
        for a in &record.assignments {
            match a.name.as_str() {
                "config name" if a.value_kind == "explicit" => {
                    config_names.insert(record.node_id.as_str(), a.value.clone());
                }
                "mbd_comp_name" if a.value_kind == "explicit" => {
                    let last = a.value.rsplit('/').next().unwrap_or(&a.value).trim();
                    if !last.is_empty() {
                        mbd_name = Some(last.to_owned());
                    }
                }
                // HOOPS Exchange based writers name components with a plain
                // `name` option (and `display name`); mbd_comp_name wins.
                "name" if a.value_kind == "explicit" => {
                    let value = a.value.trim();
                    if !value.is_empty() && !value.chars().any(char::is_control) {
                        plain_name = Some(value.to_owned());
                    }
                }
                // Millimetres per model unit (1 = mm, 1000 = m, 25.4 = inch), as
                // written next to `hefiletype`; SOLIDWORKS writers omit it.
                "model_units" if a.value_kind == "explicit" => {
                    if let Ok(v) = a.value.trim().parse::<f64>()
                        && v.is_finite()
                        && v > 0.0
                        && model_units.is_none()
                    {
                        model_units = Some(v);
                    }
                }
                "defaultcolor" if a.value_kind == "explicit" => {
                    let parts: Vec<f32> = a
                        .value
                        .split_whitespace()
                        .filter_map(|v| v.parse().ok())
                        .collect();
                    if parts.len() == 3 && parts.iter().all(|v| v.is_finite()) {
                        color = Some(
                            [parts[0], parts[1], parts[2]]
                                .map(|v| (v.clamp(0.0, 1.0) * 255.0).round() as u8),
                        );
                    }
                }
                "defaulttransmission" if a.value_kind == "explicit" => {
                    transmission = a.value.trim().parse::<f32>().unwrap_or(0.0).clamp(0.0, 1.0);
                }
                _ => {}
            }
        }
        if let Some(rgb) = color {
            let alpha = (255.0 * (1.0 - transmission)).round() as u8;
            default_colors.insert(record.node_id.as_str(), [rgb[0], rgb[1], rgb[2], alpha]);
        }
        if let Some(name) = mbd_name {
            option_names.insert(record.node_id.as_str(), name);
        } else if let Some(name) = plain_name {
            option_names.entry(record.node_id.as_str()).or_insert(name);
        }
    }
    // The model's own name: the `model_root` segment's name entry or option.
    let model_name = nodes
        .iter()
        .find(|n| {
            n.name.as_deref() == Some("model_root")
                && n.parent_id
                    .as_deref()
                    .and_then(|p| node_index.get(p).copied())
                    == Some(root)
        })
        .and_then(|n| {
            index_names
                .get(&n.id)
                .cloned()
                .or_else(|| option_names.get(n.id.as_str()).cloned())
        });
    // Component names stored as text primitives under a `name` child segment.
    let mut text_names: HashMap<usize, String> = HashMap::new();
    for p in &data.primitives {
        let Some(text) = p.text.as_ref().and_then(|t| t.value.clone()) else {
            continue;
        };
        let Some(&owner) = node_index.get(p.owner_node_id.as_str()) else {
            continue;
        };
        if nodes[owner].name.as_deref() != Some("name") {
            continue;
        }
        let Some(parent) = nodes[owner]
            .parent_id
            .as_deref()
            .and_then(|id| node_index.get(id).copied())
        else {
            continue;
        };
        let trimmed = text.trim();
        if !trimmed.is_empty() && !trimmed.chars().any(char::is_control) {
            text_names
                .entry(parent)
                .or_insert_with(|| trimmed.to_owned());
        }
    }
    budget.charge_output((option_records.len() + text_names.len()) as u64 * 256)?;

    // Configurations: configN children of the root.
    let mut config_nodes: Vec<usize> = nodes
        .iter()
        .enumerate()
        .filter(|(_, n)| {
            !n.implicit
                && numbered(n.name.as_deref(), "config")
                && n.parent_id
                    .as_deref()
                    .and_then(|p| node_index.get(p).copied())
                    == Some(root)
        })
        .map(|(i, _)| i)
        .collect();
    config_nodes.sort_by_key(|&i| number(nodes[i].name.as_deref().unwrap_or(""), "config"));
    let config_name = |i: usize| config_names.get(nodes[i].id.as_str()).cloned();
    // A configuration the writer hid with a face-visibility-off record on its own
    // segment; the one left visible is the active (current) configuration.
    let config_hidden = |i: usize| nodes[i].face_visible.as_ref().is_some_and(|a| !a.value);
    let any_hidden = config_nodes.iter().any(|&i| config_hidden(i));
    let active = config_nodes.iter().copied().find(|&i| !config_hidden(i));
    let records_by_node: HashMap<&str, Vec<&UserOptionRecord>> =
        option_records.iter().fold(HashMap::new(), |mut m, r| {
            m.entry(r.node_id.as_str()).or_default().push(r);
            m
        });
    let child_named = |parent: usize, name: &str| -> Option<usize> {
        nodes.iter().position(|n| {
            n.name.as_deref() == Some(name)
                && n.parent_id
                    .as_deref()
                    .and_then(|p| node_index.get(p).copied())
                    == Some(parent)
        })
    };
    let option_value = |node: usize, key: &str| -> Option<String> {
        records_by_node
            .get(nodes[node].id.as_str())?
            .iter()
            .flat_map(|r| r.assignments.iter())
            .find(|a| a.name == key && a.value_kind == "explicit")
            .map(|a| a.value.clone())
    };
    // The display state eDrawings shows for a configuration: `current`, else
    // `default`, from its `displaystates` child segment.
    let display_state = |i: usize| -> Option<String> {
        let ds = child_named(i, "displaystates")?;
        option_value(ds, "current").or_else(|| option_value(ds, "default"))
    };
    let (selected, selection) = if config_nodes.is_empty() {
        (None, "none")
    } else if let Some(wanted) = &options.configuration {
        let found = config_nodes.iter().copied().find(|&i| {
            config_name(i).as_deref() == Some(wanted.as_str())
                || nodes[i].name.as_deref() == Some(wanted.as_str())
        });
        match found {
            Some(i) => (Some(i), "explicit"),
            None => {
                return Err(Error::invalid(
                    "display.configuration_unknown",
                    "display",
                    "Requested configuration matches no saved configN segment or config name",
                ));
            }
        }
    } else if any_hidden && let Some(i) = active {
        (Some(i), "active")
    } else {
        (Some(config_nodes[0]), "first")
    };
    // Saved display states of a configuration: `dispN` children of its
    // `displaystates` segment, with an optional `name` option.
    let display_states = |i: usize| -> Vec<(usize, DisplayState)> {
        let Some(ds) = child_named(i, "displaystates") else {
            return Vec::new();
        };
        let current = option_value(ds, "current");
        let default = option_value(ds, "default");
        let mut states: Vec<(usize, DisplayState)> = nodes
            .iter()
            .enumerate()
            .filter(|(_, n)| {
                numbered(n.name.as_deref(), "disp")
                    && n.parent_id
                        .as_deref()
                        .and_then(|p| node_index.get(p).copied())
                        == Some(ds)
            })
            .map(|(k, n)| {
                let segment = n.name.clone().unwrap_or_default();
                let components = nodes
                    .iter()
                    .filter(|m| {
                        numbered(m.name.as_deref(), "comp")
                            && m.parent_id
                                .as_deref()
                                .and_then(|p| node_index.get(p).copied())
                                == Some(k)
                    })
                    .count() as u64;
                let state = DisplayState {
                    current: current.as_deref() == Some(segment.as_str()),
                    default: default.as_deref() == Some(segment.as_str()),
                    name: option_value(k, "name"),
                    components,
                    segment_name: segment,
                };
                (k, state)
            })
            .collect();
        states.sort_by_key(|(_, s)| number(&s.segment_name, "disp"));
        states
    };
    // Display-state overrides of the shown configuration: `compN` segments under
    // `displaystates/<state>` carry `path=<segment path>,vis=on|off`. The state is
    // the requested one, else `current`, else `default`.
    let mut visibility_overrides: HashMap<usize, bool> = HashMap::new();
    let mut shown_state: Option<String> = None;
    let mut state_selection = "none";
    let mut state_node: Option<usize> = None;
    if let Some(c) = selected {
        let states = display_states(c);
        if let Some(wanted) = &options.display_state {
            let found = states.iter().find(|(_, s)| {
                s.segment_name == *wanted || s.name.as_deref() == Some(wanted.as_str())
            });
            match found {
                Some((k, s)) => {
                    state_node = Some(*k);
                    shown_state = Some(s.segment_name.clone());
                    state_selection = "explicit";
                }
                None => {
                    return Err(Error::invalid(
                        "display.display_state_unknown",
                        "display",
                        "Requested display state matches no dispN segment or display state name of the shown configuration",
                    ));
                }
            }
        } else if let Some((k, s)) = states.iter().find(|(_, s)| s.current) {
            state_node = Some(*k);
            shown_state = Some(s.segment_name.clone());
            state_selection = "current";
        } else if let Some((k, s)) = states.iter().find(|(_, s)| s.default) {
            state_node = Some(*k);
            shown_state = Some(s.segment_name.clone());
            state_selection = "default";
        }
    }
    if let Some(state_node) = state_node {
        let path_index: HashMap<&str, usize> = paths
            .iter()
            .enumerate()
            .map(|(i, p)| (p.as_str(), i))
            .collect();
        for (k, n) in nodes.iter().enumerate() {
            if n.parent_id
                .as_deref()
                .and_then(|p| node_index.get(p).copied())
                != Some(state_node)
            {
                continue;
            }
            let (Some(path), Some(vis)) = (option_value(k, "path"), option_value(k, "vis")) else {
                continue;
            };
            let normalized = format!(
                "/{}",
                path.split('/')
                    .filter(|s| !s.is_empty())
                    .map(component_name)
                    .collect::<Vec<_>>()
                    .join("/")
            );
            if let Some(&target) = path_index.get(normalized.as_str()) {
                budget.charge_output(64)?;
                visibility_overrides.insert(target, vis.eq_ignore_ascii_case("on"));
            }
        }
    }
    let default_visibility: HashMap<&str, bool> = option_records
        .iter()
        .flat_map(|r| {
            r.assignments
                .iter()
                .filter(|a| a.name == "defaultvisibility" && a.value_kind == "explicit")
                .map(move |a| (r.node_id.as_str(), !a.value.eq_ignore_ascii_case("off")))
        })
        .collect();
    // The configuration marker (face visibility off on a configN segment) selects
    // configurations; it is not component visibility. Default visibility is the
    // deepest own face flag below the shown configuration's segment.
    let mut above_selected: std::collections::HashSet<usize> = std::collections::HashSet::new();
    if let Some(mut c) = selected {
        loop {
            above_selected.insert(c);
            match nodes[c]
                .parent_id
                .as_deref()
                .and_then(|p| node_index.get(p).copied())
            {
                Some(p) => c = p,
                None => break,
            }
        }
    }
    let config_ids: HashMap<&str, usize> = config_nodes
        .iter()
        .map(|&i| (nodes[i].id.as_str(), i))
        .collect();
    let mut config_counts: HashMap<usize, u64> = HashMap::new();

    // Bodies: meshes with triangles, in mesh order.
    let mut body_of_mesh: HashMap<&str, u32> = HashMap::new();
    let mut bodies: Vec<DisplayBody> = Vec::new();
    let mut buffers: Vec<BodyBuffers> = Vec::new();
    let null_by_mesh: HashMap<&str, &str> = data
        .null_shells
        .iter()
        .filter(|n| n.instance_of.is_none())
        .filter_map(|n| n.mesh_id.as_deref().map(|m| (m, n.id.as_str())))
        .collect();
    for m in &data.meshes {
        if m.triangles.is_empty() {
            continue;
        }
        budget.charge_output(
            m.vertices.len() as u64 * 12
                + m.normals.len() as u64 * 12
                + m.triangles.len() as u64 * (12 + 64)
                + 1024,
        )?;
        let edges = outline_edges(&m.triangles, &m.triangle_faces);
        budget.charge_output(edges.len() as u64 * 8)?;
        let owner = node_index.get(m.owner_node_id.as_str()).copied();
        body_of_mesh.insert(m.id.as_str(), bodies.len() as u32);
        bodies.push(DisplayBody {
            index: bodies.len() as u32,
            mesh_id: format!("{entry}/{}", m.id),
            null_shell_id: null_by_mesh
                .get(m.id.as_str())
                .map(|n| format!("{entry}/{n}")),
            source_node_id: format!("{entry}/{}", m.owner_node_id),
            source_node_path: owner.map(|o| paths[o].clone()).unwrap_or_default(),
            vertex_count: m.vertices.len() as u32,
            triangle_count: m.triangles.len() as u32,
            edge_count: edges.len() as u32,
            has_normals: m.normals.len() == m.vertices.len() && !m.normals.is_empty(),
            bounds: m.bounds,
            instance_count: 0,
            name: None,
        });
        buffers.push(BodyBuffers {
            positions: m.vertices.clone(),
            normals: if m.normals.len() == m.vertices.len() {
                m.normals.clone()
            } else {
                vec![]
            },
            triangles: m.triangles.clone(),
            edges,
        });
    }

    // Colours from materials.xml, keyed by entity name.
    let mut materials: HashMap<String, Material> = HashMap::new();
    let mut materials_entry_id = None;
    if options.colors == ColorPolicy::MaterialsXml
        && let Some(e) = doc
            .inspection()
            .entries
            .iter()
            .find(|e| e.role == "metadata" && e.raw_name == b"materials.xml")
    {
        materials_entry_id = Some(e.id.clone());
        match doc
            .extract_budget(&e.id, budget)
            .and_then(|x| parse_materials(&x.data, limits))
        {
            Ok(map) => {
                budget.charge_output(map.len() as u64 * 128)?;
                materials = map;
            }
            Err(error) => diagnostics.push(warning(
                &entry,
                "edrawings.materials_unreadable",
                format!("materials.xml was not used for colours: {error}"),
            )),
        }
    }
    let material_for = |owner: usize| -> Option<&Material> {
        // Nearest node first; entity names are stored relative (`shared/body1/body1sub0`).
        let mut current = Some(owner);
        let mut hops = 0;
        while let Some(i) = current {
            hops += 1;
            if hops > 64 {
                break;
            }
            let path = paths[i].trim_start_matches('/');
            let parts: Vec<&str> = path.split('/').filter(|s| !s.is_empty()).collect();
            for start in 0..parts.len() {
                if let Some(m) = materials.get(&parts[start..].join("/")) {
                    return Some(m);
                }
            }
            current = nodes[i]
                .parent_id
                .as_deref()
                .and_then(|p| node_index.get(p).copied());
        }
        None
    };

    // Instances.
    let mut instances = InstanceBuffers::default();
    let mut names: Vec<String> = Vec::new();
    let mut name_index: HashMap<String, u32> = HashMap::new();
    let mut component_paths: Vec<String> = Vec::new();
    let mut component_index: HashMap<String, u32> = HashMap::new();
    let intern =
        |table: &mut Vec<String>, index: &mut HashMap<String, u32>, value: String| -> u32 {
            if let Some(&i) = index.get(&value) {
                return i;
            }
            let i = table.len() as u32;
            table.push(value.clone());
            index.insert(value, i);
            i
        };
    let mut stats = DisplayStatistics {
        records,
        processed_records: processed,
        nodes: nodes.len() as u64,
        meshes: data.meshes.len() as u64,
        bodies: bodies.len() as u64,
        instances: 0,
        instances_before_configuration_filter: data.instances.len() as u64,
        faces_off_instances: 0,
        hidden_instances: 0,
        hidden_bodies: 0,
        line_only_instances_skipped: 0,
        triangles: 0,
        unplaced_bodies: 0,
        colors_from_hsf: 0,
        colors_from_materials: 0,
        colors_from_options: 0,
        stopped_record_id: stopped_record_id.clone(),
        unparsed_bytes,
    };
    budget.charge_output(data.instances.len() as u64 * 256)?;
    let mut placed: Vec<u32> = vec![0; bodies.len()];
    for inst in &data.instances {
        let path_nodes: Vec<usize> = inst
            .path
            .iter()
            .filter_map(|id| node_index.get(id.as_str()).copied())
            .collect();
        let config_hit = path_nodes
            .iter()
            .find_map(|i| config_ids.get(nodes[*i].id.as_str()).copied());
        if let Some(c) = config_hit {
            *config_counts.entry(c).or_default() += 1;
        }
        if let Some(selected) = selected
            && config_hit.is_some_and(|c| c != selected)
        {
            continue;
        }
        let Some(&body) = body_of_mesh.get(inst.mesh_id.as_str()) else {
            stats.line_only_instances_skipped += 1;
            continue;
        };
        // Names along the component chain (before the include): component texts,
        // mbd_comp_name / name options and User Index Data `name` entries, with
        // consecutive repeats (occurrence and prototype) collapsed. Names inside
        // the included subtree belong to the body itself.
        let cut = inst
            .path
            .iter()
            .position(|p| p.starts_with("reference:"))
            .unwrap_or(inst.path.len());
        let name_of = |i: usize| -> Option<String> {
            text_names
                .get(&i)
                .cloned()
                .or_else(|| option_names.get(nodes[i].id.as_str()).cloned())
                .or_else(|| index_names.get(&nodes[i].id).cloned())
        };
        let mut chain: Vec<String> = Vec::new();
        let mut body_name: Option<String> = None;
        for (k, id) in inst.path.iter().enumerate() {
            let Some(&i) = node_index.get(id.as_str()) else {
                continue;
            };
            let Some(n) = name_of(i) else {
                continue;
            };
            if k < cut {
                if chain.last() != Some(&n) {
                    chain.push(n);
                }
            } else {
                body_name = Some(n);
            }
        }
        if let Some(b) = &body_name
            && bodies[body as usize].name.is_none()
        {
            bodies[body as usize].name = Some(b.clone());
        }
        let name = match chain.last() {
            Some(n) => n.clone(),
            None if body_name.is_some() => body_name.clone().unwrap_or_default(),
            None => {
                // The including segment (just before the first reference) or the owner.
                let including = inst
                    .path
                    .iter()
                    .position(|p| p.starts_with("reference:"))
                    .and_then(|k| k.checked_sub(1))
                    .and_then(|k| node_index.get(inst.path[k].as_str()).copied());
                let fallback = including.or_else(|| node_index.get(inst.node_id.as_str()).copied());
                fallback
                    .and_then(|i| nodes[i].name.as_deref().map(component_name))
                    .unwrap_or_default()
            }
        };
        let component_path = chain.join("/");
        let face_visibility = match inst.face_visible.as_ref() {
            None => 2,
            Some(a) if a.value => 1,
            Some(_) => 0,
        };
        if face_visibility == 0 {
            stats.faces_off_instances += 1;
        }
        // Effective visibility: the deepest display-state override on the chain
        // wins; else the deepest `defaultvisibility` option; else the stored
        // HSF face flag (eDrawings writes both for hidden components).
        let overridden = inst
            .path
            .iter()
            .rev()
            .filter_map(|id| node_index.get(id.as_str()))
            .find_map(|i| visibility_overrides.get(i).copied());
        let defaulted = inst
            .path
            .iter()
            .rev()
            .filter_map(|id| default_visibility.get(id.as_str()))
            .next()
            .copied();
        let own_flag = if selected.is_some() {
            inst.path
                .iter()
                .rev()
                .filter_map(|id| node_index.get(id.as_str()).copied())
                .filter(|i| !above_selected.contains(i))
                .find_map(|i| nodes[i].face_visible.as_ref().map(|a| a.value))
                .unwrap_or(true)
        } else {
            face_visibility != 0
        };
        let shown = overridden.or(defaulted).unwrap_or(own_flag);
        placed[body as usize] += 1;
        if !shown {
            stats.hidden_instances += 1;
            if !options.include_hidden {
                continue;
            }
        }
        let owner = node_index.get(inst.node_id.as_str()).copied();
        let (color, source_code) = if let Some(c) = &inst.face_color {
            stats.colors_from_hsf += 1;
            ([c.value[0], c.value[1], c.value[2], 255], COLOR_SOURCE_HSF)
        } else if options.colors == ColorPolicy::MaterialsXml
            && let Some(m) = owner.and_then(material_for)
        {
            stats.colors_from_materials += 1;
            (
                [m.rgb[0], m.rgb[1], m.rgb[2], m.alpha],
                COLOR_SOURCE_MATERIALS,
            )
        } else if options.colors == ColorPolicy::MaterialsXml
            && let Some(c) = path_nodes
                .iter()
                .rev()
                .find_map(|i| default_colors.get(nodes[*i].id.as_str()))
        {
            stats.colors_from_options += 1;
            (*c, COLOR_SOURCE_OPTION)
        } else {
            ([0, 0, 0, 0], COLOR_SOURCE_NONE)
        };
        instances.matrices.push(inst.world_transform);
        instances.bodies.push(body);
        instances.colors.push(color);
        instances.color_sources.push(source_code);
        instances.face_visibility.push(face_visibility);
        instances.visibility.push(u8::from(shown));
        instances
            .names
            .push(intern(&mut names, &mut name_index, name));
        instances.component_paths.push(intern(
            &mut component_paths,
            &mut component_index,
            component_path,
        ));
        bodies[body as usize].instance_count += 1;
        stats.triangles += u64::from(bodies[body as usize].triangle_count);
    }
    stats.instances = instances.bodies.len() as u64;
    stats.unplaced_bodies = placed.iter().filter(|&&n| n == 0).count() as u64;
    stats.hidden_bodies = bodies
        .iter()
        .zip(&placed)
        .filter(|(b, n)| **n > 0 && b.instance_count == 0)
        .count() as u64;
    budget.charge_output(
        names
            .iter()
            .chain(&component_paths)
            .map(|s| s.len() as u64 + 32)
            .sum::<u64>()
            + instances.bodies.len() as u64 * 160,
    )?;

    let configurations = DisplayConfigurations {
        candidates: config_nodes
            .iter()
            .map(|&i| DisplayConfiguration {
                node_id: format!("{entry}/{}", nodes[i].id),
                segment_name: nodes[i].name.clone().unwrap_or_default(),
                name: config_name(i),
                instances: config_counts.get(&i).copied().unwrap_or(0),
                hidden: config_hidden(i),
                display_state: display_state(i),
                display_states: display_states(i).into_iter().map(|(_, s)| s).collect(),
            })
            .collect(),
        selected_node_id: selected.map(|i| format!("{entry}/{}", nodes[i].id)),
        active_node_id: if any_hidden {
            active.map(|i| format!("{entry}/{}", nodes[i].id))
        } else {
            None
        },
        selection: selection.into(),
        shown_display_state: shown_state.clone(),
        display_state_selection: state_selection.into(),
    };
    if let Some(i) = selected {
        diagnostics.push(info(
            &entry,
            "edrawings.display_configuration_selected",
            format!(
                "Showing configuration {} ({}) selected by {}; {} saved configurations",
                nodes[i].name.as_deref().unwrap_or(""),
                config_name(i).unwrap_or_default(),
                selection,
                config_nodes.len()
            ),
        ));
    }
    if options.placement == PlacementPolicy::SceneGraphV1
        && data.placement_status != hsf_core::Status::Complete
    {
        diagnostics.push(info(
            &entry,
            "edrawings.display_placement_estimated",
            format!(
                "{} instances are placed from the stored segment tree, modelling matrices, includes and repeats; the producer's own arrangement is not verified",
                stats.instances
            ),
        ));
    }
    if stats.hidden_instances > 0 {
        diagnostics.push(info(
            &entry,
            "edrawings.display_hidden_components",
            format!(
                "{} placed instances are hidden by eDrawings ({} inherit a face-visibility-off flag; display state {}); they are {} the buffers",
                stats.hidden_instances,
                stats.faces_off_instances,
                shown_state.as_deref().unwrap_or("none"),
                if options.include_hidden { "kept in" } else { "left out of" }
            ),
        ));
    }
    if stats.unplaced_bodies > 0 {
        diagnostics.push(warning(
            &entry,
            "edrawings.display_unplaced_bodies",
            format!(
                "{} bodies have no instance in the shown configuration",
                stats.unplaced_bodies
            ),
        ));
    }
    if stats.line_only_instances_skipped > 0 {
        diagnostics.push(info(
            &entry,
            "edrawings.display_line_only_skipped",
            format!(
                "{} instances of meshes without triangles are not in the bundle",
                stats.line_only_instances_skipped
            ),
        ));
    }
    diagnostics.push(info(
        &entry,
        "edrawings.display_colors",
        format!(
            "Colours: {} from inherited HSF colour, {} from materials.xml, {} from defaultcolor options, {} without colour",
            stats.colors_from_hsf,
            stats.colors_from_materials,
            stats.colors_from_options,
            stats.instances - stats.colors_from_hsf - stats.colors_from_materials - stats.colors_from_options
        ),
    ));

    // Preview image.
    let mut preview = None;
    let mut preview_entry_id = None;
    let mut preview_media_type = None;
    if let Some(e) = doc
        .inspection()
        .entries
        .iter()
        .find(|e| e.role == "preview")
    {
        let media = if e.raw_name.ends_with(b".png") {
            "image/png"
        } else {
            "image/jpeg"
        };
        match doc.extract_budget(&e.id, budget) {
            Ok(x) => {
                preview_entry_id = Some(e.id.clone());
                preview_media_type = Some(media.to_string());
                preview = Some((Arc::from(x.data), media.to_string()));
            }
            Err(error) => diagnostics.push(warning(
                &entry,
                "edrawings.preview_unreadable",
                format!("The preview image was not extracted: {error}"),
            )),
        }
    }
    budget.charge_output(16384)?;
    let writer_year_hint = header_strings[0]
        .as_deref()
        .and_then(|s| s.get(..4))
        .and_then(|s| s.parse::<u16>().ok())
        .filter(|y| (1990..=2100).contains(y));
    let summary = DisplaySummary {
        document: DisplayDocument {
            entry_id: entry.clone(),
            hsf_version,
            writer: header_strings[1].clone(),
            writer_year_hint,
            configuration_candidate: header_strings[2].clone(),
            revision_history: header_strings[3].clone(),
            mount_path,
            user_data_profile,
            preview_entry_id,
            preview_media_type,
            materials_entry_id,
            model_name,
            model_units,
        },
        placement_policy: options.placement,
        placement_status: status(data.placement_status),
        status: status(scene.status),
        configurations,
        bodies,
        instance_count: stats.instances,
        names,
        component_paths,
        statistics: stats,
        diagnostics,
        usage: HsfUsage {
            input_bytes: budget.usage().input_bytes,
            expanded_bytes: budget.usage().expanded_bytes,
            output_bytes: budget.usage().output_bytes,
        },
    };
    Ok(DisplayResult {
        summary,
        bodies: buffers,
        instances,
        preview,
    })
}
