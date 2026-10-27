use serde::{Deserialize, Serialize};

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Status {
    NotRequested,
    Complete,
    Partial,
    Unsupported,
    Invalid,
    LimitExceeded,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ByteRange {
    pub offset: u64,
    pub length: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct SourceRef {
    pub file_sha256: String,
    pub entry_id: String,
    pub domain_id: String,
    pub decoded_range: ByteRange,
    /// Corresponding whole compressed block, not a byte-wise offset mapping.
    pub container_range: ByteRange,
    pub encoding: String,
    pub payload_sha256: String,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct Diagnostic {
    pub code: String,
    pub severity: String,
    pub classification: Status,
    pub stage: String,
    pub entry_id: Option<String>,
    pub domain_id: Option<String>,
    pub byte_range: Option<ByteRange>,
    pub message: String,
    pub opcode: Option<u8>,
    pub hsf_version: Option<String>,
    pub impact: Option<String>,
}
impl Diagnostic {
    pub fn new(code: &str, classification: Status, stage: &str, message: &str) -> Self {
        Self {
            code: code.into(),
            severity: "error".into(),
            classification,
            stage: stage.into(),
            entry_id: None,
            domain_id: None,
            byte_range: None,
            message: message.into(),
            opcode: None,
            hsf_version: None,
            impact: None,
        }
    }
    pub fn at(mut self, offset: u64, length: u64) -> Self {
        self.domain_id = Some("file".into());
        self.byte_range = Some(ByteRange { offset, length });
        self
    }
    pub fn entry(mut self, id: &str) -> Self {
        self.entry_id = Some(id.into());
        self
    }
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum InputKind {
    RawHsf,
    Zip,
    PrefixedZip,
    Unknown,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Header {
    pub text: String,
    pub version: String,
    pub major: u16,
    pub minor: u16,
    pub byte_len: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ProbeResult {
    pub input_kind: InputKind,
    pub evidence: Vec<String>,
    pub header: Option<Header>,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntryInfo {
    pub id: String,
    pub ordinal: usize,
    pub name: String,
    pub raw_name: Vec<u8>,
    pub name_encoding: String,
    pub role: String,
    pub compressed_bytes: u64,
    pub bytes: u64,
    pub compression_method: u16,
    pub flag_bits: u16,
    pub crc32: Option<String>,
    pub crc_status: String,
    pub header_range: ByteRange,
    pub data_range: ByteRange,
    pub extraction_status: Status,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Stages {
    pub container: Status,
    pub metadata: Status,
    pub hsf_header: Status,
    pub hsf_syntax: Status,
    pub scene: Status,
    pub drawing: Status,
}
impl Default for Stages {
    fn default() -> Self {
        Self {
            container: Status::Complete,
            metadata: Status::NotRequested,
            hsf_header: Status::NotRequested,
            hsf_syntax: Status::NotRequested,
            scene: Status::NotRequested,
            drawing: Status::NotRequested,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Inspection {
    pub input_kind: InputKind,
    pub document_kind: String,
    pub filename_hint: Option<String>,
    pub file_bytes: u64,
    pub file_sha256: String,
    pub prefix_bytes: u64,
    pub zip_offset_base: Option<u64>,
    pub entries: Vec<EntryInfo>,
    pub hsf_candidates: Vec<String>,
    pub header: Option<Header>,
    pub stages: Stages,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ExtractionInfo {
    pub entry_id: String,
    pub bytes: u64,
    pub sha256: String,
    pub crc_status: String,
    pub source: SourceRef,
}
#[derive(Clone, Debug)]
pub struct Extraction {
    pub data: Vec<u8>,
    pub info: ExtractionInfo,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct XmlMetadata {
    pub entry_id: String,
    pub root_name: String,
    pub elements: u64,
    pub max_depth: u64,
    pub syntax_status: Status,
    pub semantic_status: Status,
    pub source: SourceRef,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HsfInspection {
    pub entry_id: String,
    pub header: Header,
    pub header_status: Status,
    pub syntax_status: Status,
    pub unparsed_range: ByteRange,
    pub source: SourceRef,
    pub diagnostics: Vec<Diagnostic>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct BuildInfo {
    pub version: String,
    pub hsf_version: String,
    pub contract_version: u32,
    pub capabilities: Vec<String>,
    pub hsf_source_sha256: String,
    pub hsf_syntax_versions: Vec<String>,
    pub hsf_syntax_opcodes: Vec<u8>,
    pub hsf_scene_features: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct HsfSpan {
    pub domain_id: String,
    pub offset: u64,
    pub length: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HsfDomain {
    pub id: String,
    pub byte_len: u64,
    pub sha256: String,
    pub parent: Option<HsfSpan>,
    pub encoding: String,
    pub parsed_bytes: u64,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct HsfRecord {
    pub rendering: Option<RenderingLayout>,
    pub camera: Option<CameraLayout>,
    pub texture: Option<TextureLayout>,
    pub image: Option<ImageLayout>,
    pub indexed_color: Option<IndexedColorLayout>,
    pub color_map: Option<ColorMapLayout>,
    pub mesh: Option<GridMeshLayout>,
    pub line_weight: Option<MarkerSizeLayout>,
    pub edge_weight: Option<MarkerSizeLayout>,
    pub named_style: Option<NamedStyleLayout>,
    pub clip_region: Option<ClipRegionLayout>,
    pub user_index: Option<UserIndexLayout>,
    pub visibility: Option<VisibilityLayout>,
    pub line_style: Option<LineStyleLayout>,
    pub glyph: Option<GlyphLayout>,
    pub font: Option<FontLayout>,
    pub marker_size: Option<MarkerSizeLayout>,
    pub view: Option<ViewLayout>,
    pub id: String,
    pub opcode: u8,
    pub kind: String,
    pub source: HsfSpan,
    pub scope: Option<String>,
    pub payload: Option<HsfSpan>,
    pub condition: Option<HsfSpan>,
    pub value: Option<u32>,
    pub shell: Option<ShellLayout>,
    pub poly_polyline: Option<PolyPolylineLayout>,
    pub primitive: Option<PrimitiveLayout>,
    pub user_data: Option<UserDataLayout>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HsfUsage {
    pub input_bytes: u64,
    pub expanded_bytes: u64,
    pub output_bytes: u64,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct HsfSummary {
    pub entry_id: String,
    pub header: Header,
    pub stages: Stages,
    pub source: SourceRef,
    pub records: Vec<HsfRecord>,
    pub domains: Vec<HsfDomain>,
    pub unparsed: Vec<HsfSpan>,
    pub diagnostics: Vec<Diagnostic>,
    pub usage: HsfUsage,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ShellLayout {
    pub null: bool,
    pub flags: u8,
    pub extended_flags: u16,
    pub refinement_index: Option<u32>,
    pub lod: u8,
    pub vertex_count: u32,
    pub vertices: HsfSpan,
    pub face_value_count: u32,
    pub face_bits: u8,
    pub faces: HsfSpan,
    pub normals: Option<HsfSpan>,
    pub attributes: Vec<ShellAttributeLayout>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MeshInfo {
    /// Definition owner, not a world placement or a document role.
    pub owner_node_id: String,
    pub vertex_normals: Option<VertexNormals>,
    pub entity_metadata: Option<EntityMetadata>,
    pub refinement: Option<ShellRefinement>,
    pub vertex_parameters: Option<VertexParameters>,
    pub id: String,
    pub source: HsfSpan,
    pub source_record_id: String,
    pub vertex_count: u64,
    pub face_value_count: u64,
    pub triangle_count: u64,
    pub normal_count: u64,
    pub topology: String,
    pub triangulation: Status,
    pub bounds: Option<[[f32; 3]; 2]>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SceneAttribute<T> {
    pub value: T,
    pub source: HsfSpan,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SceneNode {
    pub implicit: bool,
    pub world_handedness: Option<SceneAttribute<Handedness>>,
    pub display: DisplayAttributes,
    pub id: String,
    pub name: Option<String>,
    pub name_source: Option<HsfSpan>,
    pub parent_id: Option<String>,
    pub source: Option<HsfSpan>,
    pub local_transform: Option<SceneAttribute<[f64; 16]>>,
    pub face_color: Option<SceneAttribute<[u8; 3]>>,
    pub face_visible: Option<SceneAttribute<bool>>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SceneReference {
    pub id: String,
    pub node_id: String,
    pub target_id: Option<String>,
    pub source: HsfSpan,
    pub kind: String,
    pub transform: Option<[f64; 16]>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SceneInstance {
    pub display: DisplayAttributes,
    pub world_handedness: Option<SceneAttribute<Handedness>>,
    pub id: String,
    pub mesh_id: String,
    pub node_id: String,
    pub path: Vec<String>,
    pub world_transform: [f64; 16],
    pub determinant: f64,
    pub face_color: Option<SceneAttribute<[u8; 3]>>,
    pub face_visible: Option<SceneAttribute<bool>>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SceneSummary {
    pub shell_parameter_sets: Vec<ShellParameterSet>,
    pub import_context: Option<SceneImportContext>,
    pub null_shells: Vec<NullShell>,
    pub rendering_options: Vec<RenderingOptions>,
    pub line_styles: Vec<LineStyleDefinition>,
    pub glyphs: Vec<GlyphDefinition>,
    pub fonts: Vec<FontDefinition>,
    pub views: Vec<NamedView>,
    pub cameras: Vec<SegmentCamera>,
    pub textures: Vec<TextureDefinition>,
    pub images: Vec<ImageDefinition>,
    pub segment_aliases: Vec<SegmentAlias>,
    pub style_segments: Vec<StyleSegmentReference>,
    pub style_resolutions: Vec<StyleResolution>,
    pub texture_uses: Vec<TextureUse>,
    pub opaque_user_data: Vec<OpaqueUserData>,
    pub placement_status: Status,
    pub primitives: Vec<PrimitiveInfo>,
    pub primitive_instances: Vec<PrimitiveInstance>,
    pub user_options: Vec<UserOptions>,
    pub user_indices: Vec<UserIndices>,
    pub hsf: HsfSummary,
    pub status: Status,
    pub units: Option<String>,
    pub meshes: Vec<MeshInfo>,
    pub nodes: Vec<SceneNode>,
    pub references: Vec<SceneReference>,
    pub instances: Vec<SceneInstance>,
    pub processed_records: u64,
    pub diagnostics: Vec<Diagnostic>,
    pub usage: HsfUsage,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PrimitiveLayout {
    pub point_count: u32,
    pub points: HsfSpan,
    pub center: Option<HsfSpan>,
    pub encoding: Option<u8>,
    pub text: Option<HsfSpan>,
    pub text_region: Option<TextRegionLayout>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextRegionLayout {
    pub options: u8,
    pub point_count: u32,
    pub points: HsfSpan,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TextValue {
    pub encoding: String,
    pub encoding_code: Option<u8>,
    pub source: HsfSpan,
    pub value: Option<String>,
    pub status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PrimitiveInfo {
    pub id: String,
    pub owner_node_id: String,
    pub kind: String,
    pub source: HsfSpan,
    pub source_record_id: String,
    pub points_source: HsfSpan,
    pub point_count: u32,
    pub part_lengths: Vec<u32>,
    pub center: Option<SceneAttribute<[f32; 3]>>,
    pub text: Option<TextValue>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DisplayAttributes {
    pub text_anchor: Option<SceneAttribute<EnumeratedValue>>,
    pub text_justification: Option<SceneAttribute<EnumeratedValue>>,
    pub line_pattern: Option<SceneAttribute<LinePattern>>,
    pub edge_pattern: Option<SceneAttribute<LinePattern>>,
    pub marker_symbol: Option<SceneAttribute<MarkerSymbol>>,
    pub texture_matrix: Option<SceneAttribute<[f64; 16]>>,
    pub colors: [Option<SceneAttribute<[u8; 3]>>; 32],
    pub visibility: [Option<SceneAttribute<bool>>; 32],
    pub marker_size: Option<SceneAttribute<MarkerSize>>,
    pub line_weight: Option<SceneAttribute<MarkerSize>>,
    pub edge_weight: Option<SceneAttribute<MarkerSize>>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct PrimitiveInstance {
    pub world_handedness: Option<SceneAttribute<Handedness>>,
    pub id: String,
    pub primitive_id: String,
    pub node_id: String,
    pub path: Vec<String>,
    pub world_transform: [f64; 16],
    pub determinant: f64,
    pub display: DisplayAttributes,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct UserOptions {
    pub node_id: String,
    pub source_record_id: String,
    pub text: TextValue,
}
/// One stored assignment, before application semantics or attribute inheritance.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct UserOptionAssignment {
    /// ASCII option name folded to lowercase; values retain their case.
    pub name: String,
    pub value: String,
    pub value_kind: String,
    pub source: HsfSpan,
    pub name_source: HsfSpan,
    /// Explicit value without surrounding quotes, including empty values.
    pub value_source: Option<HsfSpan>,
    pub value_token_source: Option<HsfSpan>,
}
/// Atomic parse of one User/Unicode Options record. Not a net attribute map.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct UserOptionRecord {
    pub node_id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub parsing_status: Status,
    pub reason: Option<String>,
    pub assignments: Vec<UserOptionAssignment>,
}
/// Geometry inventory and document semantics have independent completion states.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DrawingAssessment {
    pub status: Status,
    pub sheet_status: Status,
    pub view_status: Status,
    pub dimension_status: Status,
    pub configuration_status: Status,
    pub component_status: Status,
    pub diagnostics: Vec<Diagnostic>,
}
#[derive(Debug, Serialize)]
pub struct DrawingSummary<'a> {
    pub assessment: &'a DrawingAssessment,
    pub scene: &'a SceneSummary,
    pub user_option_records: &'a [UserOptionRecord],
    pub component_inventory: &'a ComponentInventory,
    pub configuration_inventory: &'a ConfigurationInventory,
    pub sheet_inventory: &'a SheetInventory,
    pub drawing_plane_profile: &'a DrawingPlaneProfile,
}

/// Raw root length option. Its code is distinct from the private header code.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DrawingLengthOption {
    pub raw_value: String,
    pub source: HsfSpan,
    pub source_record_id: String,
}
/// Exact four-byte code in the verified private header, not a global HSF unit.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DrawingHeaderUnit {
    pub raw_value: u32,
    pub source: HsfSpan,
    pub source_record_id: String,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DrawingLengthUnit {
    Millimeter,
    Centimeter,
    Meter,
    Inch,
}
/// Bounded DXF writer plane convention. Does not change placement/strict status,
/// interpret Z, recover a CAD origin, unscale views, or synthesize cameras.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct DrawingPlaneProfile {
    pub profile: String,
    pub status: Status,
    pub reason: Option<String>,
    pub root_length: Option<DrawingLengthOption>,
    pub header_unit: Option<DrawingHeaderUnit>,
    pub source_length_unit: Option<DrawingLengthUnit>,
    pub stored_xy_unit: Option<DrawingLengthUnit>,
    pub xy_meters_per_saved_unit: Option<f64>,
    pub source_units_to_meters: Option<f64>,
    pub z_semantics: String,
    pub cad_origin: String,
}

/// One explicit, unambiguous stored name assignment; no inherited/effective name.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredDrawingName {
    pub value: String,
    pub encoding: String,
    pub source: HsfSpan,
    pub source_record_id: String,
}
/// Root-level sheet convention, in source order, not native SheetIndex order.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredSheet {
    pub node_id: String,
    pub segment_name: String,
    pub segment_name_source: HsfSpan,
    pub name: StoredDrawingName,
    pub view_node_ids: Vec<String>,
    /// Definitions under this node, including views; references are not expanded.
    pub primitive_ids: Vec<String>,
    pub mesh_ids: Vec<String>,
}
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum StoredDrawingViewKind {
    View,
    BorderView,
}
/// Saved view grouping, distinct from an HSF NamedView/camera or projection.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredDrawingView {
    pub node_id: String,
    pub sheet_node_id: String,
    pub segment_name: String,
    pub segment_name_source: HsfSpan,
    pub kind: StoredDrawingViewKind,
    pub name: StoredDrawingName,
    pub model_2d_node_id: Option<String>,
    pub model_3d_node_id: Option<String>,
    pub primitive_ids: Vec<String>,
    pub mesh_ids: Vec<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SheetInventory {
    pub profile: String,
    /// Coverage of the recognized stored convention, not document semantics.
    pub status: Status,
    pub reason: Option<String>,
    pub sheets: Vec<StoredSheet>,
    pub views: Vec<StoredDrawingView>,
}

/// Stored text with its original geometry definition identity and source.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ComponentText {
    pub primitive_id: String,
    pub text: TextValue,
}
/// Original matrix on a component's direct `part` child; not world placement.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredPartTransform {
    pub part_node_id: String,
    pub matrix: SceneAttribute<[f64; 16]>,
}
/// A saved component node, excluding Reader-generated document/config roots.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredComponent {
    pub node_id: String,
    pub parent_component_node_id: Option<String>,
    pub root_node_id: String,
    pub relative_path: String,
    pub name: ComponentText,
    pub reference_name: ComponentText,
    pub reference_path: ComponentText,
    pub part_transform: Option<StoredPartTransform>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ComponentInventory {
    pub profile: String,
    /// Coverage of the saved text convention, not native active-state or placement qualification.
    pub status: Status,
    pub reason: Option<String>,
    pub components: Vec<StoredComponent>,
}
/// Saved configuration group; source order does not claim a public API index.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StoredConfiguration {
    pub node_id: String,
    pub segment_name: String,
    pub segment_name_source: HsfSpan,
    pub name: StoredDrawingName,
    pub component_node_ids: Vec<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ConfigurationInventory {
    pub profile: String,
    pub status: Status,
    pub reason: Option<String>,
    pub configurations: Vec<StoredConfiguration>,
    pub active_configuration_node_id: Option<String>,
}

/// Experimental application layout; fields are raw spans, not product properties.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct UserDataLayout {
    pub profile: String,
    pub declared_length: u32,
    pub computed_payload_length: u32,
    pub evidence_level: String,
    pub native_reader_verified: bool,
    pub fields: Vec<UserDataField>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct UserDataField {
    pub label: String,
    pub source: HsfSpan,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Handedness {
    Left,
    Right,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ViewLayout {
    pub projection: u8,
    pub camera: HsfSpan,
    pub name: HsfSpan,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct Camera {
    pub projection_bits: u8,
    pub projection: String,
    pub stretched: bool,
    pub position: [f32; 3],
    pub target: [f32; 3],
    pub up_vector: [f32; 3],
    pub field_width: f32,
    pub field_height: f32,
    pub oblique_y_degrees: Option<f32>,
    pub oblique_x_degrees: Option<f32>,
    pub near_limit: Option<f32>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NamedView {
    pub id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub context_node_id: String,
    pub name: TextValue,
    pub camera_source: HsfSpan,
    pub camera: Camera,
    pub status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct OpaqueUserData {
    pub source_record_id: String,
    pub source: HsfSpan,
    pub profile: String,
}

/// Raw masks include extension flags; only mask-selected geometry bits apply.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct VisibilityLayout {
    pub mask: u32,
    pub value: u32,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct LineStyleLayout {
    pub name: HsfSpan,
    pub definition: HsfSpan,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct FontLayout {
    pub format: u8,
    pub name: HsfSpan,
    /// Glyph mapping code, not the encoding of the name or lookup string.
    pub encoding: u8,
    pub lookup: HsfSpan,
    pub data: HsfSpan,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct MarkerSizeLayout {
    /// Exact IEEE-754 wire bits, including negative zero.
    pub value_bits: u32,
    pub units: Option<u8>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MarkerSize {
    pub value: f32,
    /// relative, object, screen, window, points, or pixels; no model-unit conversion.
    pub units: String,
}

/// Ordered definition events. Names do not select an active line pattern.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LineStyleDefinition {
    pub program: Option<LineStyleProgram>,
    pub reason: Option<String>,
    pub id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub context_node_id: String,
    pub name: TextValue,
    pub definition: TextValue,
    pub interpretation_status: Status,
}

/// Font bytes and lookup identifiers are retained, never executed or loaded.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FontDefinition {
    pub id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub context_node_id: String,
    pub format: u8,
    pub name: TextValue,
    pub encoding: u8,
    pub lookup: TextValue,
    pub data_source: HsfSpan,
    pub interpretation_status: Status,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct OperandField {
    pub name: String,
    pub encoding: String,
    pub source: HsfSpan,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct RenderingLayout {
    pub mask: u64,
    /// Heuristics/Text Font/Rendering Options values; Color channel mask.
    pub value: u64,
    pub fields: Vec<OperandField>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct NullShell {
    pub mesh_id: Option<String>,
    pub id: String,
    pub node_id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub lod: u8,
}

/// Ordered settings, linked to framed operands. No effective rendering is claimed.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RenderingOptions {
    pub glyph_binding: Option<GlyphBinding>,
    pub settings: Option<RenderingSettings>,
    pub line_style_binding: Option<LineStyleBinding>,
    pub node_id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub kind: String,
    pub interpretation_status: Status,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct NamedStyleLayout {
    pub index: Option<u16>,
    pub name: Option<HsfSpan>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ClipRegionLayout {
    pub options: u8,
    pub point_count: u32,
    pub points: HsfSpan,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct UserIndexLayout {
    pub count: u32,
    /// Signed 32-bit arrays, stored separately (not interleaved pairs).
    pub indices: HsfSpan,
    pub values: HsfSpan,
}

/// Segment metadata; signed arrays remain source-backed. No application IDs inferred.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct UserIndices {
    pub node_id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub layout: UserIndexLayout,
    pub interpretation_status: Status,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct CameraLayout {
    pub projection: u8,
    pub settings: HsfSpan,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct TextureLayout {
    pub name: HsfSpan,
    pub image: HsfSpan,
    pub flags: u32,
    pub fields: Vec<OperandField>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct IndexedColorLayout {
    pub geometry_mask: u32,
    pub index: u16,
}
/// Source-backed RGB8 palette; lookup and inheritance remain unevaluated.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ColorMapLayout {
    pub format: u8,
    pub entry_count: u32,
    pub colors: HsfSpan,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct GridMeshLayout {
    pub flags: u8,
    pub rows: u32,
    pub columns: u32,
    pub vertex_count: u32,
    pub vertices: HsfSpan,
    pub attributes: Vec<GridAttributeLayout>,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct GridAttributeLayout {
    pub opcode: u8,
    pub source: HsfSpan,
    pub width: u8,
    pub bits_per_sample: Option<u8>,
    pub bounds: Option<HsfSpan>,
    /// Raw f32s or packed octets; texture coordinates are not evaluated.
    pub values: HsfSpan,
}

/// Ordered camera assignments to a segment. No projection matrix or CAD sheet is inferred.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SegmentCamera {
    pub node_id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub camera_source: HsfSpan,
    pub camera: Camera,
    pub status: Status,
}

/// Named image references only: never load external files, URLs or texture code.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TextureDefinition {
    pub options: TextureOptions,
    pub id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub context_node_id: String,
    pub name: TextValue,
    pub image: TextValue,
    /// Byte-identical names in the consumed scene prefix, including later images.
    /// These are candidates only: no scope, time, override or rendering binding.
    pub image_name_matches: Vec<String>,
    pub flags: u32,
    pub interpretation_status: Status,
}

/// Stored all-vertex normals in local coordinates. No normalization or transform.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VertexNormals {
    pub count: u32,
    pub source: HsfSpan,
    pub values_source: HsfSpan,
    pub encoding: String,
    pub compression: Option<u8>,
    pub bits_per_sample: Option<u8>,
    pub packing: String,
    /// Implicit quantization bounds; empty for uncompressed XYZ.
    pub bounds: Vec<[f32; 2]>,
}
/// Ordered geometry-level user strings; product-specific keys remain opaque.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntityMetadata {
    pub source: HsfSpan,
    pub fields: Vec<EntityMetadataField>,
    pub decoding_status: Status,
    pub interpretation_status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EntityMetadataField {
    pub kind: String,
    pub text: TextValue,
}

/// Raw or dequantized all-vertex parameters, before texture transforms or sampling.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct VertexParameters {
    pub quantization: Option<ParameterQuantization>,
    pub width: u8,
    pub count: u32,
    pub source: HsfSpan,
    pub values_source: HsfSpan,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ParameterQuantization {
    pub bits_per_sample: u8,
    pub packing: String,
    pub bounds: Vec<[f32; 2]>,
    pub bounds_source: HsfSpan,
}
/// Parameters in a refinement's own vertex order with an optional geometry binding.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ShellParameterSet {
    pub mesh_id: Option<String>,
    pub id: String,
    pub node_id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub vertices_source: HsfSpan,
    pub refinement_index: Option<u32>,
    pub lod: u8,
    pub target_id: Option<String>,
    pub association_status: Status,
    pub association_reason: Option<String>,
    pub vertex_parameters: VertexParameters,
    pub interpretation_status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ShellRefinement {
    pub index: u32,
    pub lod: u8,
    pub context_node_id: String,
    pub target_id: String,
    pub target_node_id: String,
    pub application_status: Status,
    pub application_reason: Option<String>,
    pub attribute_status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TextureOptions {
    pub enumerations: Vec<TextureEnum>,
    pub value_scale: Option<SceneAttribute<[f32; 2]>>,
    pub transform_segment: Option<TextValue>,
    pub parameter_offset: Option<SceneAttribute<u8>>,
    pub unevaluated_flags: u32,
    pub decoding_status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TextureEnum {
    pub name: String,
    pub raw: u8,
    pub value: Option<String>,
    pub source: HsfSpan,
}

/// Ordered explicit diffuse-texture request, not the final net material.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TextureUse {
    pub id: String,
    pub node_id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub geometry_mask: u32,
    pub specification: TextValue,
    pub texture_name: Option<TextValue>,
    pub diffuse_color: Option<SceneAttribute<[f32; 3]>>,
    pub binding: TextureBinding,
    pub interpretation_status: Status,
}
/// Unique local implicit-image association, not a texture option or draw result.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct TextureBinding {
    pub scope: String,
    pub status: Status,
    pub reason: Option<String>,
    pub image_id: Option<String>,
    pub texture_definition_ids: Vec<String>,
    pub style_path: Vec<String>,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct PolyPolylineLayout {
    pub flags: u16,
    pub point_count: u32,
    pub primitive_count: u32,
    pub dimensions: u8,
    pub lengths: HsfSpan,
    pub points: HsfSpan,
    pub leftovers: HsfSpan,
}
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ShellAttributeLayout {
    pub opcode: u8,
    pub source: HsfSpan,
    pub fields: Vec<OperandField>,
}

/// Encoded image inventory. Pixel decoding, color space and placement are unverified.
#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
pub struct ImageLayout {
    pub profile: String,
    pub position: HsfSpan,
    pub format_options: u32,
    pub name: HsfSpan,
    pub width: u32,
    pub height: u32,
    pub compression: u8,
    pub data: HsfSpan,
    pub alpha_compression: u8,
    pub alpha: HsfSpan,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SegmentAlias {
    pub alias: String,
    pub target_path: String,
    /// First use of this assumed default binding, not a definition in the file.
    pub source_record_id: String,
    pub source: HsfSpan,
    pub interpretation_status: Status,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StyleSegmentReference {
    pub id: String,
    pub node_id: String,
    /// Existing target at the opcode; no forward lookup.
    pub target_id: Option<String>,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub path: TextValue,
    pub condition: Option<TextValue>,
    pub interpretation_status: Status,
}

/// Final local-plus-style display subset; excludes parent, defaults and external state.
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct StyleResolution {
    pub node_id: String,
    pub style_ids: Vec<String>,
    pub display: Option<DisplayAttributes>,
    pub status: Status,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct ImageDefinition {
    pub id: String,
    pub node_id: String,
    pub source_record_id: String,
    pub source: HsfSpan,
    pub profile: String,
    pub name: TextValue,
    /// Stored reference point, not a world placement or a pixel-size transform.
    pub position: SceneAttribute<[f32; 3]>,
    pub format_options: u32,
    pub implicit_texture_local: bool,
    pub width: u32,
    pub height: u32,
    pub compression: u8,
    /// Encoded JPEG; no entropy decoding or pixel allocation is performed.
    pub data_source: HsfSpan,
    pub alpha_compression: u8,
    pub alpha_source: HsfSpan,
    pub interpretation_status: Status,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct SceneImportContext {
    pub requested_root: String,
    pub resolved_root: String,
    pub node_id: String,
    /// Nodes introduced by the caller context, including the modeled global root.
    /// They have no file source and do not prove external attributes or geometry.
    pub context_node_ids: Vec<String>,
    pub interpretation_status: Status,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LinePattern {
    pub binding: Option<LineStyleBinding>,
    /// Original packed pattern/cap/join word, absent for a named assignment.
    pub index: Option<u16>,
    pub name: Option<TextValue>,
    pub pattern: Option<String>,
    pub cap: Option<String>,
    pub join: Option<String>,
    pub interpretation_status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct MarkerSymbol {
    pub binding: Option<GlyphBinding>,
    pub index: Option<u16>,
    pub name: Option<TextValue>,
    pub symbol: Option<String>,
    pub interpretation_status: Status,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LineStyleProgram {
    /// solid, explicit_dash_blank, parallel_dash_blank, or extended_line_style.
    pub kind: String,
    /// Contract 26 simple form. Empty for parallel_dash_blank.
    pub elements: Vec<LineStyleElement>,
    pub parallels: Vec<LineStyleParallel>,
    pub transformed_source: Option<HsfSpan>,
    pub interpretation_status: Status,
    pub reason: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LineStyleElement {
    pub kind: String,
    /// None means an explicitly unsized, stretchable dash/blank.
    pub length: Option<f64>,
    pub units: Option<String>,
    pub stretchable: bool,
    pub source: HsfSpan,
    pub length_source: Option<HsfSpan>,
    pub units_source: Option<HsfSpan>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LineStyleParallel {
    pub source: HsfSpan,
    /// None for the implicit first parallel.
    pub marker_source: Option<HsfSpan>,
    pub elements: Vec<LineStyleElement>,
    pub weight: Option<LineStyleMeasure>,
    pub offset: Option<LineStyleMeasure>,
    pub segmented_source: Option<HsfSpan>,
    pub fit: Option<LineStyleFit>,
    pub absolute_length_source: Option<HsfSpan>,
    pub absolute_weight_source: Option<HsfSpan>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LineStyleFit {
    pub mode: String,
    pub source: HsfSpan,
    pub value_source: HsfSpan,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LineStyleMeasure {
    pub value: f64,
    /// None preserves an omitted weight unit; interpretation stays unsupported.
    pub units: Option<String>,
    pub fixed: bool,
    pub source: HsfSpan,
    pub value_source: HsfSpan,
    pub units_source: Option<HsfSpan>,
    pub fixed_source: Option<HsfSpan>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct LineStyleBinding {
    pub scope: String,
    pub definition_id: Option<String>,
    pub status: Status,
    pub reason: Option<String>,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct EnumeratedValue {
    pub index: u8,
    pub name: Option<String>,
    pub interpretation_status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RenderingOperand {
    pub name: String,
    pub encoding: String,
    pub source: HsfSpan,
    pub floats: Vec<f32>,
    pub integers: Vec<i64>,
    pub text: Option<TextValue>,
    pub enumeration: Option<EnumeratedValue>,
    pub decoding_status: Status,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct FontFlag {
    pub name: String,
    pub bit: u32,
    pub value: bool,
    pub source: HsfSpan,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct RenderingSettings {
    pub mask: u64,
    pub value: u64,
    pub operands: Vec<RenderingOperand>,
    pub font_flags: Vec<FontFlag>,
    pub decoding_status: Status,
    pub interpretation_status: Status,
}

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GlyphDefinition {
    pub id: String,
    pub source_record_id: String,
    pub context_node_id: String,
    pub source: HsfSpan,
    pub name: TextValue,
    pub definition_source: HsfSpan,
    pub program: Option<GlyphProgram>,
    pub interpretation_status: Status,
    pub reason: Option<String>,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GlyphProgram {
    pub nominal_radius: u8,
    pub offset: [i16; 2],
    pub header_source: HsfSpan,
    pub commands: Vec<GlyphCommand>,
    pub termination_source: HsfSpan,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct GlyphCommand {
    pub code: i16,
    pub kind: String,
    pub points: Vec<[i16; 2]>,
    pub color: Vec<u8>,
    pub source: HsfSpan,
    pub payload_source: HsfSpan,
}
pub type GlyphBinding = LineStyleBinding;

pub type GlyphLayout = LineStyleLayout;
