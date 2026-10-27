"""Immutable public models. Status describes a processing stage, not format support."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, fields, is_dataclass
from functools import lru_cache
from typing import Any, Literal, TypeVar, cast, get_args, get_origin, get_type_hints

Status = Literal[
    "not_requested", "complete", "partial", "unsupported", "invalid", "limit_exceeded"
]
InputKind = Literal["raw_hsf", "zip", "prefixed_zip", "unknown"]
T = TypeVar("T")


@dataclass(frozen=True)
class Model:
    def to_dict(self) -> dict[str, Any]:
        # JSON-normalized representation agrees exactly with the Rust schema.
        return cast(dict[str, Any], json.loads(json.dumps(asdict(self))))


@dataclass(frozen=True)
class ByteRange(Model):
    offset: int
    length: int


@dataclass(frozen=True)
class SourceRef(Model):
    file_sha256: str
    entry_id: str
    domain_id: str
    decoded_range: ByteRange
    container_range: ByteRange
    encoding: str
    payload_sha256: str


@dataclass(frozen=True)
class Diagnostic(Model):
    code: str
    severity: str
    classification: Status
    stage: str
    entry_id: str | None
    domain_id: str | None
    byte_range: ByteRange | None
    message: str
    opcode: int | None
    hsf_version: str | None
    impact: str | None


@dataclass(frozen=True)
class Header(Model):
    text: str
    version: str
    major: int
    minor: int
    byte_len: int


@dataclass(frozen=True)
class ProbeResult(Model):
    input_kind: InputKind
    evidence: tuple[str, ...]
    header: Header | None
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class EntryInfo(Model):
    id: str
    ordinal: int
    name: str
    raw_name: tuple[int, ...]
    name_encoding: str
    role: str
    compressed_bytes: int
    bytes: int
    compression_method: int
    flag_bits: int
    crc32: str | None
    crc_status: str
    header_range: ByteRange
    data_range: ByteRange
    extraction_status: Status


@dataclass(frozen=True)
class Stages(Model):
    container: Status
    metadata: Status
    hsf_header: Status
    hsf_syntax: Status
    scene: Status
    drawing: Status


@dataclass(frozen=True)
class Inspection(Model):
    input_kind: InputKind
    document_kind: str
    filename_hint: str | None
    file_bytes: int
    file_sha256: str
    prefix_bytes: int
    zip_offset_base: int | None
    entries: tuple[EntryInfo, ...]
    hsf_candidates: tuple[str, ...]
    header: Header | None
    stages: Stages
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class ExtractionInfo(Model):
    entry_id: str
    bytes: int
    sha256: str
    crc_status: str
    source: SourceRef


@dataclass(frozen=True)
class Extraction:
    data: bytes
    info: ExtractionInfo


@dataclass(frozen=True)
class XmlMetadata(Model):
    entry_id: str
    root_name: str
    elements: int
    max_depth: int
    syntax_status: Status
    semantic_status: Status
    source: SourceRef


@dataclass(frozen=True)
class HsfInspection(Model):
    entry_id: str
    header: Header
    header_status: Status
    syntax_status: Status
    unparsed_range: ByteRange
    source: SourceRef
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class BuildInfo(Model):
    version: str
    hsf_version: str
    contract_version: int
    capabilities: tuple[str, ...]
    hsf_source_sha256: str
    hsf_syntax_versions: tuple[str, ...]
    hsf_syntax_opcodes: tuple[int, ...]
    hsf_scene_features: tuple[str, ...]


@dataclass(frozen=True)
class HsfSpan(Model):
    domain_id: str
    offset: int
    length: int


@dataclass(frozen=True)
class HsfDomain(Model):
    id: str
    byte_len: int
    sha256: str
    parent: HsfSpan | None
    encoding: str
    parsed_bytes: int


@dataclass(frozen=True)
class HsfRecord(Model):
    rendering: RenderingLayout | None
    camera: CameraLayout | None
    texture: TextureLayout | None
    image: ImageLayout | None
    indexed_color: IndexedColorLayout | None
    color_map: ColorMapLayout | None
    mesh: GridMeshLayout | None
    line_weight: MarkerSizeLayout | None
    edge_weight: MarkerSizeLayout | None
    named_style: NamedStyleLayout | None
    clip_region: ClipRegionLayout | None
    user_index: UserIndexLayout | None
    visibility: VisibilityLayout | None
    line_style: LineStyleLayout | None
    glyph: GlyphLayout | None
    font: FontLayout | None
    marker_size: MarkerSizeLayout | None
    view: ViewLayout | None
    id: str
    opcode: int
    kind: str
    source: HsfSpan
    scope: str | None
    payload: HsfSpan | None
    condition: HsfSpan | None
    value: int | None
    shell: ShellLayout | None
    poly_polyline: PolyPolylineLayout | None
    primitive: PrimitiveLayout | None
    user_data: UserDataLayout | None


@dataclass(frozen=True)
class HsfUsage(Model):
    input_bytes: int
    expanded_bytes: int
    output_bytes: int


@dataclass(frozen=True)
class HsfSummary(Model):
    entry_id: str
    header: Header
    stages: Stages
    source: SourceRef
    records: tuple[HsfRecord, ...]
    domains: tuple[HsfDomain, ...]
    unparsed: tuple[HsfSpan, ...]
    diagnostics: tuple[Diagnostic, ...]
    usage: HsfUsage


@lru_cache(maxsize=128)
def _model_hints(cls: type[Any]) -> dict[str, Any]:
    # Cache schema metadata only, never input values or source bytes. Large
    # streams contain many records of the same immutable model classes.
    return get_type_hints(cls)


def _convert(annotation: Any, value: Any) -> Any:
    if value is None:
        return None
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is tuple:
        return tuple(_convert(args[0], item) for item in value)
    if type(None) in args:
        return _convert(next(arg for arg in args if arg is not type(None)), value)
    if isinstance(annotation, type) and is_dataclass(annotation):
        hints = _model_hints(annotation)
        return annotation(
            **{
                field.name: _convert(hints[field.name], value[field.name])
                for field in fields(annotation)
            }
        )
    return value


def _decode(cls: type[T], text: str) -> T:
    return cast(T, _convert(cls, json.loads(text)))


@dataclass(frozen=True)
class ShellLayout(Model):
    null: bool
    flags: int
    extended_flags: int
    refinement_index: int | None
    lod: int
    vertex_count: int
    vertices: HsfSpan
    face_value_count: int
    face_bits: int
    faces: HsfSpan
    normals: HsfSpan | None
    attributes: tuple[ShellAttributeLayout, ...]


@dataclass(frozen=True)
class NumericBuffer:
    data: bytes
    dtype: Literal["<f4", "<i4", "<u4"]
    shape: tuple[int, ...]


@dataclass(frozen=True)
class MeshBuffers:
    vertices: NumericBuffer
    face_list: NumericBuffer
    triangles: NumericBuffer
    triangle_faces: NumericBuffer
    normals: NumericBuffer | None
    parameters: NumericBuffer | None = None


@dataclass(frozen=True)
class MeshInfo(Model):
    """Local mesh definition; owner_node_id does not assert world placement."""

    owner_node_id: str
    vertex_normals: VertexNormals | None
    entity_metadata: EntityMetadata | None
    refinement: ShellRefinement | None
    vertex_parameters: VertexParameters | None
    id: str
    source: HsfSpan
    source_record_id: str
    vertex_count: int
    face_value_count: int
    triangle_count: int
    normal_count: int
    topology: str
    triangulation: Status
    bounds: tuple[tuple[float, ...], ...] | None


@dataclass(frozen=True)
class MatrixAttribute(Model):
    value: tuple[float, ...]
    source: HsfSpan


@dataclass(frozen=True)
class ColorAttribute(Model):
    value: tuple[int, ...]
    source: HsfSpan


@dataclass(frozen=True)
class VisibilityAttribute(Model):
    value: bool
    source: HsfSpan


@dataclass(frozen=True)
class SceneNode(Model):
    implicit: bool
    world_handedness: HandednessAttribute | None
    display: DisplayAttributes
    id: str
    name: str | None
    name_source: HsfSpan | None
    parent_id: str | None
    source: HsfSpan | None
    local_transform: MatrixAttribute | None
    face_color: ColorAttribute | None
    face_visible: VisibilityAttribute | None


@dataclass(frozen=True)
class SceneReference(Model):
    id: str
    node_id: str
    target_id: str | None
    source: HsfSpan
    kind: str
    transform: tuple[float, ...] | None


@dataclass(frozen=True)
class SceneInstance(Model):
    display: DisplayAttributes
    world_handedness: HandednessAttribute | None
    id: str
    mesh_id: str
    node_id: str
    path: tuple[str, ...]
    world_transform: tuple[float, ...]
    determinant: float
    face_color: ColorAttribute | None
    face_visible: VisibilityAttribute | None


@dataclass(frozen=True)
class SceneSummary(Model):
    shell_parameter_sets: tuple[ShellParameterSet, ...]
    import_context: SceneImportContext | None
    null_shells: tuple[NullShell, ...]
    rendering_options: tuple[RenderingOptions, ...]
    line_styles: tuple[LineStyleDefinition, ...]
    glyphs: tuple[GlyphDefinition, ...]
    fonts: tuple[FontDefinition, ...]
    views: tuple[NamedView, ...]
    cameras: tuple[SegmentCamera, ...]
    textures: tuple[TextureDefinition, ...]
    images: tuple[ImageDefinition, ...]
    segment_aliases: tuple[SegmentAlias, ...]
    style_segments: tuple[StyleSegmentReference, ...]
    style_resolutions: tuple[StyleResolution, ...]
    texture_uses: tuple[TextureUse, ...]
    opaque_user_data: tuple[OpaqueUserData, ...]
    placement_status: Status
    primitives: tuple[PrimitiveInfo, ...]
    primitive_instances: tuple[PrimitiveInstance, ...]
    user_options: tuple[UserOptions, ...]
    user_indices: tuple[UserIndices, ...]
    hsf: HsfSummary
    status: Status
    units: str | None
    meshes: tuple[MeshInfo, ...]
    nodes: tuple[SceneNode, ...]
    references: tuple[SceneReference, ...]
    instances: tuple[SceneInstance, ...]
    processed_records: int
    diagnostics: tuple[Diagnostic, ...]
    usage: HsfUsage


@dataclass(frozen=True)
class PrimitiveLayout(Model):
    point_count: int
    points: HsfSpan
    center: HsfSpan | None
    encoding: int | None
    text: HsfSpan | None
    text_region: TextRegionLayout | None


@dataclass(frozen=True)
class TextRegionLayout(Model):
    """Raw region controls and points; space and glyph layout are unevaluated."""

    options: int
    point_count: int
    points: HsfSpan


@dataclass(frozen=True)
class TextValue(Model):
    encoding: str
    encoding_code: int | None
    source: HsfSpan
    value: str | None
    status: Status


@dataclass(frozen=True)
class PointAttribute(Model):
    value: tuple[float, ...]
    source: HsfSpan


@dataclass(frozen=True)
class PrimitiveInfo(Model):
    """Local primitive definition and its owning scene node."""

    id: str
    owner_node_id: str
    kind: str
    source: HsfSpan
    source_record_id: str
    points_source: HsfSpan
    point_count: int
    part_lengths: tuple[int, ...]
    center: PointAttribute | None
    text: TextValue | None


@dataclass(frozen=True)
class DisplayAttributes(Model):
    text_anchor: EnumeratedAttribute | None
    text_justification: EnumeratedAttribute | None
    """Colors/visibility use bits 0..31; extension flags stay None."""

    colors: tuple[ColorAttribute | None, ...]
    visibility: tuple[VisibilityAttribute | None, ...]
    marker_size: MarkerSizeAttribute | None
    line_weight: MarkerSizeAttribute | None
    edge_weight: MarkerSizeAttribute | None
    texture_matrix: MatrixAttribute | None
    line_pattern: LinePatternAttribute | None
    edge_pattern: LinePatternAttribute | None
    marker_symbol: MarkerSymbolAttribute | None


@dataclass(frozen=True)
class PrimitiveInstance(Model):
    world_handedness: HandednessAttribute | None
    id: str
    primitive_id: str
    node_id: str
    path: tuple[str, ...]
    world_transform: tuple[float, ...]
    determinant: float
    display: DisplayAttributes


@dataclass(frozen=True)
class UserOptions(Model):
    node_id: str
    source_record_id: str
    text: TextValue


@dataclass(frozen=True)
class UserOptionAssignment(Model):
    name: str
    value: str
    value_kind: Literal["explicit", "implicit_on", "implicit_off"]
    source: HsfSpan
    name_source: HsfSpan
    value_source: HsfSpan | None
    value_token_source: HsfSpan | None


@dataclass(frozen=True)
class UserOptionRecord(Model):
    node_id: str
    source_record_id: str
    source: HsfSpan
    parsing_status: Status
    reason: str | None
    assignments: tuple[UserOptionAssignment, ...]


@dataclass(frozen=True)
class DrawingAssessment(Model):
    status: Status
    sheet_status: Status
    view_status: Status
    dimension_status: Status
    configuration_status: Status
    component_status: Status
    diagnostics: tuple[Diagnostic, ...]


@dataclass(frozen=True)
class DrawingSummary(Model):
    assessment: DrawingAssessment
    scene: SceneSummary
    user_option_records: tuple[UserOptionRecord, ...]
    component_inventory: ComponentInventory
    configuration_inventory: ConfigurationInventory
    sheet_inventory: SheetInventory
    drawing_plane_profile: DrawingPlaneProfile


@dataclass(frozen=True)
class DrawingLengthOption(Model):
    raw_value: str
    source: HsfSpan
    source_record_id: str


@dataclass(frozen=True)
class DrawingHeaderUnit(Model):
    raw_value: int
    source: HsfSpan
    source_record_id: str


@dataclass(frozen=True)
class DrawingPlaneProfile(Model):
    """Bounded stored XY units; no camera, CAD origin, Z or model-size inference."""

    profile: str
    status: Status
    reason: str | None
    root_length: DrawingLengthOption | None
    header_unit: DrawingHeaderUnit | None
    source_length_unit: Literal["millimeter", "centimeter", "meter", "inch"] | None
    stored_xy_unit: Literal["millimeter", "centimeter", "meter", "inch"] | None
    xy_meters_per_saved_unit: float | None
    source_units_to_meters: float | None
    z_semantics: str
    cad_origin: str


@dataclass(frozen=True)
class StoredDrawingName(Model):
    value: str
    encoding: str
    source: HsfSpan
    source_record_id: str


@dataclass(frozen=True)
class StoredSheet(Model):
    """Saved grouping in source order; geometry references are not expanded."""

    node_id: str
    segment_name: str
    segment_name_source: HsfSpan
    name: StoredDrawingName
    view_node_ids: tuple[str, ...]
    primitive_ids: tuple[str, ...]
    mesh_ids: tuple[str, ...]


@dataclass(frozen=True)
class StoredDrawingView(Model):
    """Saved view node, distinct from a camera, projection or visible instance."""

    node_id: str
    sheet_node_id: str
    segment_name: str
    segment_name_source: HsfSpan
    kind: Literal["view", "border_view"]
    name: StoredDrawingName
    model_2d_node_id: str | None
    model_3d_node_id: str | None
    primitive_ids: tuple[str, ...]
    mesh_ids: tuple[str, ...]


@dataclass(frozen=True)
class SheetInventory(Model):
    profile: str
    status: Status
    reason: str | None
    sheets: tuple[StoredSheet, ...]
    views: tuple[StoredDrawingView, ...]


@dataclass(frozen=True)
class ComponentText(Model):
    primitive_id: str
    text: TextValue


@dataclass(frozen=True)
class StoredPartTransform(Model):
    """Source matrix on a direct part child; no world placement or unit claim."""

    part_node_id: str
    matrix: MatrixAttribute


@dataclass(frozen=True)
class StoredComponent(Model):
    """Saved relative hierarchy; no Reader filename prefix or placement claim."""

    node_id: str
    parent_component_node_id: str | None
    root_node_id: str
    relative_path: str
    name: ComponentText
    reference_name: ComponentText
    reference_path: ComponentText
    part_transform: StoredPartTransform | None


@dataclass(frozen=True)
class ComponentInventory(Model):
    profile: str
    status: Status
    reason: str | None
    components: tuple[StoredComponent, ...]


@dataclass(frozen=True)
class StoredConfiguration(Model):
    """Saved group and component ownership; source order is not a native index."""

    node_id: str
    segment_name: str
    segment_name_source: HsfSpan
    name: StoredDrawingName
    component_node_ids: tuple[str, ...]


@dataclass(frozen=True)
class ConfigurationInventory(Model):
    profile: str
    status: Status
    reason: str | None
    configurations: tuple[StoredConfiguration, ...]
    active_configuration_node_id: str | None


@dataclass(frozen=True)
class UserDataField(Model):
    label: str
    source: HsfSpan


@dataclass(frozen=True)
class UserDataLayout(Model):
    profile: str
    declared_length: int
    computed_payload_length: int
    evidence_level: str
    native_reader_verified: bool
    fields: tuple[UserDataField, ...]


@dataclass(frozen=True)
class HandednessAttribute(Model):
    value: Literal["left", "right"]
    source: HsfSpan


@dataclass(frozen=True)
class ViewLayout(Model):
    projection: int
    camera: HsfSpan
    name: HsfSpan


@dataclass(frozen=True)
class Camera(Model):
    projection_bits: int
    projection: Literal["orthographic", "perspective"]
    stretched: bool
    position: tuple[float, ...]
    target: tuple[float, ...]
    up_vector: tuple[float, ...]
    field_width: float
    field_height: float
    oblique_y_degrees: float | None
    oblique_x_degrees: float | None
    near_limit: float | None


@dataclass(frozen=True)
class NamedView(Model):
    id: str
    source_record_id: str
    source: HsfSpan
    context_node_id: str
    name: TextValue
    camera_source: HsfSpan
    camera: Camera
    status: Status


@dataclass(frozen=True)
class OpaqueUserData(Model):
    source_record_id: str
    source: HsfSpan
    profile: str


@dataclass(frozen=True)
class VisibilityLayout(Model):
    mask: int
    value: int


@dataclass(frozen=True)
class LineStyleLayout(Model):
    name: HsfSpan
    definition: HsfSpan


@dataclass(frozen=True)
class FontLayout(Model):
    format: int
    name: HsfSpan
    encoding: int
    lookup: HsfSpan
    data: HsfSpan


@dataclass(frozen=True)
class MarkerSizeLayout(Model):
    value_bits: int
    units: int | None


@dataclass(frozen=True)
class MarkerSize(Model):
    value: float
    units: Literal["relative", "object", "screen", "window", "points", "pixels"]


@dataclass(frozen=True)
class MarkerSizeAttribute(Model):
    value: MarkerSize
    source: HsfSpan


@dataclass(frozen=True)
class LineStyleDefinition(Model):
    program: LineStyleProgram | None
    reason: str | None
    id: str
    source_record_id: str
    source: HsfSpan
    context_node_id: str
    name: TextValue
    definition: TextValue
    interpretation_status: Status


@dataclass(frozen=True)
class FontDefinition(Model):
    id: str
    source_record_id: str
    source: HsfSpan
    context_node_id: str
    format: int
    name: TextValue
    encoding: int
    lookup: TextValue
    data_source: HsfSpan
    interpretation_status: Status


@dataclass(frozen=True)
class OperandField(Model):
    name: str
    encoding: str
    source: HsfSpan


@dataclass(frozen=True)
class RenderingLayout(Model):
    mask: int
    value: int
    fields: tuple[OperandField, ...]


@dataclass(frozen=True)
class NullShell(Model):
    mesh_id: str | None
    id: str
    node_id: str
    source_record_id: str
    source: HsfSpan
    lod: int


@dataclass(frozen=True)
class RenderingOptions(Model):
    glyph_binding: GlyphBinding | None
    settings: RenderingSettings | None
    line_style_binding: LineStyleBinding | None
    node_id: str
    source_record_id: str
    source: HsfSpan
    kind: str
    interpretation_status: Status


@dataclass(frozen=True)
class NamedStyleLayout(Model):
    index: int | None
    name: HsfSpan | None


@dataclass(frozen=True)
class ClipRegionLayout(Model):
    options: int
    point_count: int
    points: HsfSpan


@dataclass(frozen=True)
class UserIndexLayout(Model):
    count: int
    indices: HsfSpan
    values: HsfSpan


@dataclass(frozen=True)
class UserIndices(Model):
    node_id: str
    source_record_id: str
    source: HsfSpan
    layout: UserIndexLayout
    interpretation_status: Status


@dataclass(frozen=True)
class CameraLayout(Model):
    projection: int
    settings: HsfSpan


@dataclass(frozen=True)
class TextureLayout(Model):
    name: HsfSpan
    image: HsfSpan
    flags: int
    fields: tuple[OperandField, ...]


@dataclass(frozen=True)
class IndexedColorLayout(Model):
    geometry_mask: int
    index: int


@dataclass(frozen=True)
class ColorMapLayout(Model):
    """RGB8 entries in wire order; palette lookup/inheritance is not evaluated."""

    format: int
    entry_count: int
    colors: HsfSpan


@dataclass(frozen=True)
class GridMeshLayout(Model):
    flags: int
    rows: int
    columns: int
    vertex_count: int
    vertices: HsfSpan
    attributes: tuple[GridAttributeLayout, ...]


@dataclass(frozen=True)
class GridAttributeLayout(Model):
    opcode: int
    source: HsfSpan
    width: int
    bits_per_sample: int | None
    bounds: HsfSpan | None
    values: HsfSpan


@dataclass(frozen=True)
class SegmentCamera(Model):
    node_id: str
    source_record_id: str
    source: HsfSpan
    camera_source: HsfSpan
    camera: Camera
    status: Status


@dataclass(frozen=True)
class TextureDefinition(Model):
    options: TextureOptions
    id: str
    source_record_id: str
    source: HsfSpan
    context_node_id: str
    name: TextValue
    image: TextValue
    image_name_matches: tuple[str, ...]
    flags: int
    interpretation_status: Status


@dataclass(frozen=True)
class PolyPolylineLayout(Model):
    flags: int
    point_count: int
    primitive_count: int
    dimensions: int
    lengths: HsfSpan
    points: HsfSpan
    leftovers: HsfSpan


@dataclass(frozen=True)
class ShellAttributeLayout(Model):
    opcode: int
    source: HsfSpan
    fields: tuple[OperandField, ...]


@dataclass(frozen=True)
class ImageLayout(Model):
    """Empirical framing only; encoded pixels and placement are not decoded."""

    profile: str
    position: HsfSpan
    format_options: int
    name: HsfSpan
    width: int
    height: int
    compression: int
    data: HsfSpan
    alpha_compression: int
    alpha: HsfSpan


@dataclass(frozen=True)
class SegmentAlias(Model):
    """Assumed startup binding, sourced at first use; no runtime proof."""

    alias: str
    target_path: str
    source_record_id: str
    source: HsfSpan
    interpretation_status: Status


@dataclass(frozen=True)
class StyleSegmentReference(Model):
    """Unevaluated style edge; target is resolved only at the source opcode."""

    id: str
    node_id: str
    target_id: str | None
    source_record_id: str
    source: HsfSpan
    path: TextValue
    condition: TextValue | None
    interpretation_status: Status


@dataclass(frozen=True)
class ImageDefinition(Model):
    """Encoded image and stored reference point; placement remains unsupported."""

    id: str
    node_id: str
    source_record_id: str
    source: HsfSpan
    profile: str
    name: TextValue
    position: PointAttribute
    format_options: int
    implicit_texture_local: bool
    width: int
    height: int
    compression: int
    data_source: HsfSpan
    alpha_compression: int
    alpha_source: HsfSpan
    interpretation_status: Status


@dataclass(frozen=True)
class SceneImportContext(Model):
    """Caller-supplied namespace, with no file source or external-state proof."""

    requested_root: str
    resolved_root: str
    node_id: str
    context_node_ids: tuple[str, ...]
    interpretation_status: Status


@dataclass(frozen=True)
class StyleResolution(Model):
    """Local plus style display; excludes parent, defaults and external state."""

    node_id: str
    style_ids: tuple[str, ...]
    display: DisplayAttributes | None
    status: Status
    reason: str | None


@dataclass(frozen=True)
class FloatColorAttribute(Model):
    """Normalized RGB from a supported text expression, without RGB8 conversion."""

    value: tuple[float, ...]
    source: HsfSpan


@dataclass(frozen=True)
class TextureBinding(Model):
    """Local/Style implicit-image identity; complete does not mean rendered."""

    scope: str
    status: Status
    reason: str | None
    image_id: str | None
    texture_definition_ids: tuple[str, ...]
    style_path: tuple[str, ...]


@dataclass(frozen=True)
class TextureUse(Model):
    """Ordered explicit diffuse-texture request, not the final net material."""

    id: str
    node_id: str
    source_record_id: str
    source: HsfSpan
    geometry_mask: int
    specification: TextValue
    texture_name: TextValue | None
    diffuse_color: FloatColorAttribute | None
    binding: TextureBinding
    interpretation_status: Status


@dataclass(frozen=True)
class VertexNormals(Model):
    """Stored local normals, with implicit bounds for quantized encodings."""

    count: int
    source: HsfSpan
    values_source: HsfSpan
    encoding: str
    compression: int | None
    bits_per_sample: int | None
    packing: str
    bounds: tuple[tuple[float, float], ...]


@dataclass(frozen=True)
class EntityMetadataField(Model):
    kind: str
    text: TextValue


@dataclass(frozen=True)
class EntityMetadata(Model):
    """Ordered user strings; product-specific keys are not interpreted."""

    source: HsfSpan
    fields: tuple[EntityMetadataField, ...]
    decoding_status: Status
    interpretation_status: Status


@dataclass(frozen=True)
class VertexParameters(Model):
    """Raw or dequantized all-vertex parameters, without generated UV or transforms."""

    quantization: ParameterQuantization | None
    width: int
    count: int
    source: HsfSpan
    values_source: HsfSpan


@dataclass(frozen=True)
class ParameterQuantization(Model):
    bits_per_sample: int
    packing: str
    bounds: tuple[tuple[float, float], ...]
    bounds_source: HsfSpan


@dataclass(frozen=True)
class ShellParameterSet(Model):
    """Source-local parameters with an optional geometry binding."""

    mesh_id: str | None
    id: str
    node_id: str
    source_record_id: str
    source: HsfSpan
    vertices_source: HsfSpan
    refinement_index: int | None
    lod: int
    target_id: str | None
    association_status: Status
    association_reason: str | None
    vertex_parameters: VertexParameters
    interpretation_status: Status


@dataclass(frozen=True)
class ShellRefinement(Model):
    """Null Shell LOD 0 geometry binding; attributes and placement are separate."""

    index: int
    lod: int
    context_node_id: str
    target_id: str
    target_node_id: str
    application_status: Status
    application_reason: str | None
    attribute_status: Status


@dataclass(frozen=True)
class TextureEnum(Model):
    name: str
    raw: int
    value: str | None
    source: HsfSpan


@dataclass(frozen=True)
class FloatPairAttribute(Model):
    value: tuple[float, ...]
    source: HsfSpan


@dataclass(frozen=True)
class ByteAttribute(Model):
    value: int
    source: HsfSpan


@dataclass(frozen=True)
class TextureOptions(Model):
    """Decoded stored options; no defaults, option merging or rendering implied."""

    enumerations: tuple[TextureEnum, ...]
    value_scale: FloatPairAttribute | None
    transform_segment: TextValue | None
    parameter_offset: ByteAttribute | None
    unevaluated_flags: int
    decoding_status: Status


@dataclass(frozen=True)
class LinePattern(Model):
    """Numeric pattern/cap/join or a source-backed custom-line binding."""

    binding: LineStyleBinding | None

    index: int | None
    name: TextValue | None
    pattern: str | None
    cap: str | None
    join: str | None
    interpretation_status: Status


@dataclass(frozen=True)
class MarkerSymbol(Model):
    binding: GlyphBinding | None
    index: int | None
    name: TextValue | None
    symbol: str | None
    interpretation_status: Status


@dataclass(frozen=True)
class LinePatternAttribute(Model):
    value: LinePattern
    source: HsfSpan


@dataclass(frozen=True)
class MarkerSymbolAttribute(Model):
    value: MarkerSymbol
    source: HsfSpan


@dataclass(frozen=True)
class LineStyleProgram(Model):
    kind: str
    elements: tuple[LineStyleElement, ...]
    parallels: tuple[LineStyleParallel, ...]
    transformed_source: HsfSpan | None
    interpretation_status: Status
    reason: str | None


@dataclass(frozen=True)
class LineStyleElement(Model):
    kind: str
    length: float | None
    units: str | None
    stretchable: bool
    source: HsfSpan
    length_source: HsfSpan | None
    units_source: HsfSpan | None


@dataclass(frozen=True)
class LineStyleParallel(Model):
    source: HsfSpan
    marker_source: HsfSpan | None
    elements: tuple[LineStyleElement, ...]
    weight: LineStyleMeasure | None
    offset: LineStyleMeasure | None
    segmented_source: HsfSpan | None
    fit: LineStyleFit | None
    absolute_length_source: HsfSpan | None
    absolute_weight_source: HsfSpan | None


@dataclass(frozen=True)
class LineStyleFit(Model):
    mode: str
    source: HsfSpan
    value_source: HsfSpan


@dataclass(frozen=True)
class LineStyleMeasure(Model):
    value: float
    units: str | None
    fixed: bool
    source: HsfSpan
    value_source: HsfSpan
    units_source: HsfSpan | None
    fixed_source: HsfSpan | None


@dataclass(frozen=True)
class LineStyleBinding(Model):
    scope: str
    definition_id: str | None
    status: Status
    reason: str | None


GlyphLayout = LineStyleLayout
GlyphBinding = LineStyleBinding


@dataclass(frozen=True)
class EnumeratedValue(Model):
    index: int
    name: str | None
    interpretation_status: Status


@dataclass(frozen=True)
class EnumeratedAttribute(Model):
    value: EnumeratedValue
    source: HsfSpan


@dataclass(frozen=True)
class RenderingOperand(Model):
    name: str
    encoding: str
    source: HsfSpan
    floats: tuple[float, ...]
    integers: tuple[int, ...]
    text: TextValue | None
    enumeration: EnumeratedValue | None
    decoding_status: Status


@dataclass(frozen=True)
class FontFlag(Model):
    name: str
    bit: int
    value: bool
    source: HsfSpan


@dataclass(frozen=True)
class RenderingSettings(Model):
    mask: int
    value: int
    operands: tuple[RenderingOperand, ...]
    font_flags: tuple[FontFlag, ...]
    decoding_status: Status
    interpretation_status: Status


@dataclass(frozen=True)
class GlyphDefinition(Model):
    id: str
    source_record_id: str
    context_node_id: str
    source: HsfSpan
    name: TextValue
    definition_source: HsfSpan
    program: GlyphProgram | None
    interpretation_status: Status
    reason: str | None


@dataclass(frozen=True)
class GlyphProgram(Model):
    nominal_radius: int
    offset: tuple[int, int]
    header_source: HsfSpan
    commands: tuple[GlyphCommand, ...]
    termination_source: HsfSpan


@dataclass(frozen=True)
class GlyphCommand(Model):
    code: int
    kind: str
    points: tuple[tuple[int, int], ...]
    color: tuple[int, ...]
    source: HsfSpan
    payload_source: HsfSpan
