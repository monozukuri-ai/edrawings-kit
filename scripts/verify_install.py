"""Stdlib-only smoke check: run with a freshly installed wheel outside the checkout."""

import hashlib
import importlib.metadata
import io
import json
import os
import struct
import subprocess
import sys
import zipfile
import zlib
from pathlib import Path

import edrawings_kit as ed

HSF = b";; HSF V8.05 \nI\x0c\0\0\0Z" + zlib.compress(b"(\x01aU\x03\0x=y)z") + b"\0"
stream = io.BytesIO()
with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("eModel", HSF)
    archive.writestr("preview.jpg", b"synthetic preview bytes")
doc = ed.read(stream.getvalue(), verify_all=True)
assert doc.inspect_hsf().header.version == "8.05"
assert doc.extract("entry:0").data == HSF
assert doc.extract("entry:0").info.sha256 == hashlib.sha256(HSF).hexdigest()
assert doc.inspection.stages.scene == "not_requested"
hsf = doc.parse_hsf(mode="strict")
assert hsf.summary.stages.hsf_syntax == "complete"
assert len(hsf.summary.domains) == 2
option = next(record for record in hsf.summary.records if record.kind == "user_options")
assert hsf.source_bytes(option.payload) == b"x=y"
partial = ed.read(b";; HSF V8.05 \n\xfe\0").parse_hsf()
assert partial.summary.stages.hsf_syntax == "partial"
assert partial.summary.diagnostics[0].opcode == 0xFE
# Independently authored triangle with uncompressed vertices and 8-bit faces.
triangle = (
    b";; HSF V19.10 \nS\x10\0"
    + struct.pack("<i9f", 3, 0, 0, 0, 1, 0, 0, 0, 1, 0)
    + b"\x01\x05\0\0\0\x08\x03\0\x01\x02\0"
)
scene = ed.read(triangle).read_scene(mode="strict")
assert scene.summary.status == "complete" and scene.summary.units is None
mesh = scene.summary.meshes[0]
assert mesh.owner_node_id == scene.summary.nodes[0].id
buffers = scene.mesh_buffers(mesh.id)
assert buffers.vertices.shape == (3, 3) and buffers.vertices.dtype == "<f4"
assert buffers.triangles.data == struct.pack("<3I", 0, 1, 2)
assert buffers.triangle_faces.data == bytes(4)
assert scene.source_bytes(mesh.source).startswith(b"S\x10")
label = "寸法 10 mm 🦀".encode("utf-16-le")
drawing_bytes = (
    b";; HSF V19.10 \n(\x01ax"
    + struct.pack("<3f", 1, 2, 3)
    + bytes([5, len(label)])
    + label
    + b"\0)\0"
)
drawing = ed.read(drawing_bytes).read_drawing()
assert isinstance(drawing.summary.component_inventory, ed.ComponentInventory)
assert drawing.summary.component_inventory.status == "unsupported"
assert isinstance(drawing.summary.sheet_inventory, ed.SheetInventory)
assert isinstance(drawing.summary.configuration_inventory, ed.ConfigurationInventory)
assert drawing.summary.configuration_inventory.status == "unsupported"
assert drawing.summary.configuration_inventory.active_configuration_node_id is None
assert isinstance(drawing.summary.drawing_plane_profile, ed.DrawingPlaneProfile)
assert drawing.summary.drawing_plane_profile.status == "unsupported"
assert drawing.summary.sheet_inventory.status == "unsupported"
assert drawing.summary.sheet_inventory.reason == "drawing.sheet_profile_unavailable"
assert drawing.summary.assessment.status == "partial"
assert drawing.summary.assessment.sheet_status == "unsupported"
assert drawing.summary.scene.status == "complete"
primitive = drawing.summary.scene.primitives[0]
assert primitive.owner_node_id == drawing.summary.scene.nodes[1].id
assert primitive.text.value == "寸法 10 mm 🦀"
assert drawing.source_bytes(primitive.text.source) == label
assert drawing.primitive_points(primitive.id).data == struct.pack("<3f", 1, 2, 3)
option_text = "NAME=`図面,A=B 🦀`,no hidden".encode("utf-16-le")
option_drawing = ed.read(
    b";; HSF V19.10 \n\x16"
    + struct.pack("<H", len(option_text) // 2)
    + option_text
    + b"\0"
).read_drawing()
option_record = option_drawing.summary.user_option_records[0]
assert isinstance(option_record, ed.UserOptionRecord)
assert option_record.parsing_status == "complete"
assignment = option_record.assignments[0]
assert isinstance(assignment, ed.UserOptionAssignment)
assert (assignment.name, assignment.value) == ("name", "図面,A=B 🦀")
assert option_drawing.source_bytes(assignment.value_source) == (
    "図面,A=B 🦀".encode("utf-16-le")
)
assert option_record.assignments[1].value_kind == "implicit_off"
assert option_drawing.summary.assessment.sheet_status == "unsupported"
info = ed.build_info().to_dict()
assert "stored_sheet_view_inventory" in info["capabilities"]
assert "stored_component_part_transforms" in info["capabilities"]
assert "stored_multiple_configurations" in info["capabilities"]
assert "bounded_drawing_plane_units" in info["capabilities"]
assert isinstance(info["contract_version"], int) and info["contract_version"] > 0
utf8 = "寸法確認 100 mm 🦀".encode()
utf8_scene = ed.read(
    b";; HSF V19.10 \nx"
    + struct.pack("<3f", 1, 2, 3)
    + bytes([10, len(utf8)])
    + utf8
    + b"\0\0"
).read_scene(mode="strict")
utf8_text = utf8_scene.summary.primitives[0].text
assert utf8_text.encoding == "utf_8" and utf8_text.encoding_code == 10
assert utf8_text.value == "寸法確認 100 mm 🦀"
assert utf8_scene.source_bytes(utf8_text.source) == utf8
# Shared Y values follow the unrestricted X array, grouped by component.
shared = b"\x10" + struct.pack("<H3i6f", 0x1C00, 4, 2, 2, 1, 2, 3, 4, 10, 20)
shared_scene = ed.read(b";; HSF V19.10 \n" + shared + b"\0").read_scene(mode="strict")
shared_poly = shared_scene.summary.primitives[0]
assert shared_scene.primitive_points(shared_poly.id).data == struct.pack(
    "<12f", 1, 10, 0, 2, 10, 0, 3, 20, 0, 4, 20, 0
)
shared_layout = shared_scene.summary.hsf.records[0].poly_polyline
assert shared_scene.source_bytes(shared_layout.leftovers) == struct.pack("<2f", 10, 20)
region_points = struct.pack("<6f", 0, 1, 2, 3, 4, 5)
region_text = (
    b"x" + struct.pack("<3f", 4, 5, 6) + b"\x05\x02A\0\x01\0\x02" + region_points
)
region_doc = ed.read(b";; HSF V19.10 \n" + region_text + b"\0")
region_hsf = region_doc.parse_hsf(mode="strict")
region_layout = region_hsf.summary.records[0].primitive.text_region
assert isinstance(region_layout, ed.TextRegionLayout)
assert region_hsf.source_bytes(region_layout.points) == region_points
region_scene = region_doc.read_scene().summary
assert region_scene.primitives[0].text.value == "A"
assert (
    region_scene.placement_status == "unsupported"
    and not region_scene.primitive_instances
)
# Polygon closure is implicit; palette bytes remain available without applying
# color inheritance or manufacturing a triangle fan.
polygon_points = struct.pack("<15f", 0, 0, 0, 2, 0, 0, 1, 1, 0, 2, 2, 0, 0, 2, 0)
polygon = b"G" + struct.pack("<i", 5) + polygon_points
polygon_scene = ed.read(b";; HSF V19.10 \n" + polygon + b"\0").read_scene(mode="strict")
assert polygon_scene.summary.primitives[0].kind == "polygon"
assert (
    polygon_scene.primitive_points(polygon_scene.summary.primitives[0].id).data
    == polygon_points
)
assert not polygon_scene.summary.meshes
palette = b"\x0c\0\x02\0\0\0\xff\0\0\0\xff\0"
palette_doc = ed.read(b";; HSF V19.10 \n" + palette + polygon + b"\0")
palette_hsf = palette_doc.parse_hsf(mode="strict")
color_map = palette_hsf.summary.records[0].color_map
assert isinstance(color_map, ed.ColorMapLayout) and color_map.entry_count == 2
assert palette_hsf.source_bytes(color_map.colors) == palette[6:]
palette_scene = palette_doc.read_scene().summary
assert palette_scene.rendering_options[0].kind == "color_map"
assert palette_scene.placement_status == "unsupported"
assert not palette_scene.primitive_instances
# Exercise the new opt-in through the installed native extension. Independent,
# invented first-header bytes; this is not official eDrawings validation.
private = (
    b"\xbe\x01a\x01b\0\0\x01"
    + bytes(64)
    + struct.pack("<I", 46)
    + b"\0"
    + bytes(16)
    + b"\0\x10"
    + bytes(16)
    + b"\x10"
    + bytes(16)
    + b"\x01c\0\0\x0346;\0\x18"
    + bytes(24)
    + bytes(48)
)
block = b"[" + struct.pack("<I", len(private) - 2) + private + b"]"
native_hsf = (
    b";; HSF V19.10 \nI\x04\0\0\0B\0"
    + bytes(24)
    + b"Z"
    + zlib.compress(block + b"U\x03\0x=yz")
    + b"\0"
)
native_doc = ed.read(native_hsf)
framed = native_doc.parse_hsf(user_data_profile="edrawings_first_be_v2")
record = framed.summary.records[3]
assert framed.source_bytes(record.source) == block
assert record.user_data.computed_payload_length == len(private)
assert record.user_data.native_reader_verified is False
assert framed.summary.stages.hsf_syntax == "partial"
assert framed.summary.unparsed == ()
assert framed.summary.records[4].kind == "user_options"
assert native_doc.parse_hsf().summary.domains[1].parsed_bytes == 0
try:
    native_doc.parse_hsf(mode="strict", user_data_profile="edrawings_first_be_v2")
except ed.UnsupportedFeatureError as error:
    assert error.diagnostic.code == "hsf.experimental_user_data"
else:
    raise AssertionError("Strict mode accepted experimental framing")
named = b"}\0" + struct.pack("<11f", 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 20) + b"\x07default"
vdoc = ed.read(b";; HSF V19.10 \nh\x01" + named + b"\0")
views = vdoc.read_scene(mode="strict").summary
assert views.placement_status == "complete"
assert views.views[0].camera.position == (0, 0, 1)
assert views.views[0].name.value == "default"
assert views.nodes[0].world_handedness.value == "right"
inventory = (
    ed.read(
        b";; HSF V19.10 \nI\x04\0\0\0B\0"
        + bytes(24)
        + b"Z"
        + zlib.compress(block + named + b"h\x01z")
        + b"\0"
    )
    .read_scene(user_data_profile="edrawings_first_be_v2")
    .summary
)
assert len(inventory.views) == len(inventory.opaque_user_data) == 1
assert inventory.placement_status == "unsupported"
assert inventory.processed_records == len(inventory.hsf.records)
assert not inventory.instances and not inventory.primitive_instances
# Contract 7 wire fixtures also run against the wheel rebuilt from the sdist.
display_wire = (
    b"V\x81\x01\x02\x80\x02\0\x01\x01"
    + b"+"
    + struct.pack("<f", -3)
    + b"\x04"
    + b"J\x01a\x05\0solid"
    + b"f\0\x01F\x05\0"
    + struct.pack("<i", 300)
    + bytes(300)
)
display_doc = ed.read(b";; HSF V19.10 \n" + display_wire + b"\0")
assert display_doc.parse_hsf(mode="strict").summary.unparsed == ()
display_scene = display_doc.read_scene()
attrs = display_scene.summary.nodes[0].display
assert len(attrs.visibility) == 32 and len(attrs.colors) == 32
assert attrs.visibility[9].value and attrs.visibility[24].value
assert attrs.visibility[7] is None and attrs.visibility[23] is None
assert attrs.marker_size.value == ed.MarkerSize(3, "pixels")
assert display_scene.summary.line_styles[0].definition.value == "solid"
font_definition = display_scene.summary.fonts[0]
assert font_definition.name.value == "F" and font_definition.encoding == 5
assert display_scene.source_bytes(font_definition.data_source) == bytes(300)
assert font_definition.interpretation_status == "unsupported"
assert display_scene.summary.status == "partial"
# Contract 8: actual installed parser, sources, parent creation and empty tags.
render_wire = (
    b"(\x06/a/b/c~\x81\x80\x80\x01\x01\x02\x03"
    + b"="
    + struct.pack("<fB", -2, 4)
    + b"S\x96\x02\0\0q)H\x04\0\x04\0\x01"
    + b"F\x07\x07\x03abc"
    + struct.pack("<fBfB", 1, 0, 0.1, 5)
    + b'"\x01\x01\x03red'
)
render_doc = ed.read(b";; HSF V19.10 \n" + render_wire + b"\0")
assert render_doc.parse_hsf(mode="strict").summary.unparsed == ()
render = render_doc.read_scene()
assert [n.implicit for n in render.summary.nodes] == [False, True, True, False]
assert render.summary.nodes[3].display.colors[24].value == (1, 2, 3)
assert render.summary.nodes[3].display.line_weight.value == ed.MarkerSize(2, "pixels")
assert len(render.summary.null_shells) == 1 and not render.summary.meshes
assert render.source_bytes(render.summary.null_shells[0].source) == b"S\x96\x02\0\0"
assert len(render.summary.rendering_options) == 3
assert render.summary.placement_status == "unsupported"
assert render.summary.processed_records == len(render.summary.hsf.records)
# Contract 9: extended render masks, raw selectors and source-backed arrays.
settings_wire = (
    b"\x0e"
    + struct.pack("<fB", -2, 4)
    + b"@\xff\x03abc*\x10"
    + b"-\x02\0\x0d\x03\0"
    + b"O\x01"
    + struct.pack("<i9f", 3, 0, 0, 0, 1, 0, 0, 0, 1, 0)
    + b"n"
    + struct.pack("<5i", 2, -2, 7, 123, -456)
    + b"R"
    + struct.pack("<4I2f", 0x80000000, 16, 0, 16, 0, 0.001)
)
settings_doc = ed.read(b";; HSF V19.10 \n" + settings_wire + b"\0")
settings_hsf = settings_doc.parse_hsf(mode="strict")
settings = settings_doc.read_scene()
assert settings.summary.nodes[0].display.edge_weight.value == ed.MarkerSize(2, "pixels")
assert len(settings.summary.rendering_options) == 6
assert settings.summary.placement_status == "unsupported"
index = settings.summary.user_indices[0]
assert isinstance(index, ed.UserIndices) and isinstance(
    index.layout, ed.UserIndexLayout
)
assert struct.unpack("<2i", settings.source_bytes(index.layout.values)) == (123, -456)
assert settings_hsf.summary.records[-2].rendering.mask == 0x1080000000
assert isinstance(settings_hsf.summary.records[1].named_style, ed.NamedStyleLayout)
assert isinstance(settings_hsf.summary.records[5].clip_region, ed.ClipRegionLayout)
# Contract 10: Pause is a checkpoint, segment Camera is separate from named View,
# and an uncompressed rectangular Mesh uses row-major points without a count word.
grid = b"M\0" + struct.pack("<ii12f", 2, 2, 0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 1, 0)
camera = b">\0" + struct.pack("<11f", 0, 0, 1, 0, 0, 0, 0, 1, 0, 10, 20)
continued = ed.read(
    b";; HSF V19.10 \n(\x01a\x01" + camera + grid + b"\x01)\0"
).read_scene(mode="strict")
assert len(continued.summary.cameras) == 1 and not continued.summary.views
assert isinstance(continued.summary.cameras[0], ed.SegmentCamera)
assert continued.summary.cameras[0].camera.position == (0, 0, 1)
assert continued.summary.status == "complete"
grid_info = continued.summary.meshes[0]
assert grid_info.topology == "rectangular_grid" and grid_info.triangle_count == 2
assert continued.mesh_buffers(grid_info.id).triangles.data == struct.pack(
    "<6I", 0, 2, 1, 3, 1, 2
)
texture = b"t\x03tex\x03img" + struct.pack("<H2f", 0x800, 2, 0.5)
opaque_doc = ed.read(
    b";; HSF V19.10 \n" + texture + b"?\x04flag\x09\x01\x01\x02" + grid + b"\0"
)
opaque_syntax = opaque_doc.parse_hsf(mode="strict").summary
assert isinstance(opaque_syntax.records[0].texture, ed.TextureLayout)
assert opaque_syntax.records[2].indexed_color.index == 513
assert isinstance(opaque_syntax.records[3].mesh, ed.GridMeshLayout)
opaque_scene = opaque_doc.read_scene()
assert opaque_scene.summary.textures[0].name.value == "tex"
assert opaque_scene.summary.textures[0].image.value == "img"
assert opaque_scene.summary.placement_status == "unsupported"
assert not opaque_scene.summary.instances
assert len(opaque_scene.summary.meshes) == 1
# Contract 11: grouped polyline boundaries survive dimensional reconstruction
# and tag references; a Marker retains its position without inventing a glyph.
poly = b"\x10" + struct.pack("<Hi2i10f", 0x1000, 5, 2, 3, *range(10))
progress = ed.read(
    b";; HSF V19.10 \nX" + struct.pack("<3f", 1, 2, 3) + poly + b"qr\0\0\0\0\0"
).read_scene(mode="strict")
assert progress.summary.primitives[0].kind == "marker"
part = progress.summary.primitives[1]
assert part.kind == "poly_polyline" and part.part_lengths == (2, 3)
assert progress.summary.references[0].target_id == part.id
assert progress.primitive_points(part.id).data == b"".join(
    struct.pack("<3f", 2 * i, 2 * i + 1, 0) for i in range(5)
)
assert isinstance(progress.summary.hsf.records[1].poly_polyline, ed.PolyPolylineLayout)
render = b"R" + struct.pack("<4I", 0x81000000, 0x110, 0x1000000, 0x110)
render += b"\xa0\x80\x10\0\0" + struct.pack("<2f", 0, 0.1) + b"\x02"
matrix = b"$" + struct.pack("<12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, 2, 3, 4)
settings = ed.read(b";; HSF V14.50 \n" + render + matrix + b"\0").read_scene()
assert [f.name for f in settings.summary.hsf.records[0].rendering.fields] == [
    "hidden_line_options",
    "hidden_line_hsr",
    "depth_range",
    "simple_shadow_options",
]
assert settings.summary.nodes[0].local_transform is None
assert settings.summary.placement_status == "unsupported"
if len(sys.argv) > 1:
    assert info["hsf_source_sha256"] == sys.argv[1], "Embedded HSF source differs"
if len(sys.argv) > 2:
    assert importlib.metadata.version("edrawings-kit") == sys.argv[2]
    assert info["version"] == sys.argv[3] == ed.__version__
if len(sys.argv) > 4:
    # From hsf-backend.lock.json: contract version, then the hsf-core version.
    assert info["contract_version"] == int(sys.argv[4]), "Embedded HSF contract differs"
    assert info["hsf_version"] == sys.argv[5], "Embedded hsf-core version differs"
cli = subprocess.run(
    [sys.executable, "-I", "-m", "edrawings_kit", "info"],
    check=True,
    capture_output=True,
    encoding="utf-8",
)
assert json.loads(cli.stdout) == info
console = Path(sys.executable).parent / (
    "edrawings-kit.exe" if os.name == "nt" else "edrawings-kit"
)
assert json.loads(subprocess.check_output([str(console), "info"])) == info
assert (Path(ed.__file__).parent / "_licenses/NOTICE").is_file()

# Independently authored JPEG marker envelope: framing smoke, no pixel decoding.
jpeg_envelope = bytes.fromhex(
    "ffd8 ffc0 0011 08 0001 0003 03 01 1100 02 1100 03 1100 "
    "ffda 000c 03 01 00 02 00 03 00 00 3f00 17 ff00 2a ffd9"
)
image_body = (
    b"i"
    + bytes(12)
    + struct.pack("<I", 0xA3)
    + b"\1n"
    + struct.pack("<iiBi", 3, 1, 2, len(jpeg_envelope))
    + jpeg_envelope
    + b"\0\xff"
)
image_doc = ed.read(b";; HSF V19.10 \n" + image_body + b"\0")
assert not image_doc.parse_hsf().summary.records
image_hsf = image_doc.parse_hsf(image_profile="edrawings_1910_u32_v1")
image_layout = image_hsf.summary.records[0].image
assert isinstance(image_layout, ed.ImageLayout)
assert image_hsf.source_bytes(image_layout.data) == jpeg_envelope
assert image_hsf.summary.stages.hsf_syntax == "partial"
assert not image_hsf.summary.unparsed
image_scene = image_doc.read_scene(image_profile="edrawings_1910_u32_v1")
assert image_scene.summary.processed_records == len(image_hsf.summary.records)
resource = image_scene.summary.images[0]
assert isinstance(resource, ed.ImageDefinition)
assert resource.width == 3 and resource.height == 1
assert (
    resource.implicit_texture_local and resource.interpretation_status == "unsupported"
)
assert image_scene.source_bytes(resource.data_source) == jpeg_envelope
assert not image_scene.summary.instances
image_matches = (
    ed.read(b";; HSF V19.10 \nt\1t\1n\0\0" + image_body + b"qr\0\0\0\0\0")
    .read_scene(image_profile="edrawings_1910_u32_v1")
    .summary
)
assert image_matches.textures[0].image_name_matches == (image_matches.images[0].id,)
assert image_matches.references[0].target_id == image_matches.images[0].id

# Terminal private data stays empirical, even when both domains are fully framed.
terminal = b"[" + struct.pack("<IBI", 9, 190, 46) + bytes(12) + b"]"
terminal_doc = ed.read(
    b";; HSF V19.10 \nI\4\0\0\0B\0"
    + bytes(24)
    + b"Z"
    + zlib.compress(block + b"h\0\1" + terminal + b"z")
    + b"\0"
)
old_terminal = terminal_doc.parse_hsf(user_data_profile="edrawings_first_be_v2")
new_terminal = terminal_doc.parse_hsf(user_data_profile="edrawings_be_envelope_v1")
assert old_terminal.summary.records == new_terminal.summary.records[:-3]
assert new_terminal.summary.stages.hsf_syntax == "partial"
assert not new_terminal.summary.unparsed
assert new_terminal.source_bytes(new_terminal.summary.records[-3].source) == terminal
terminal_scene = terminal_doc.read_scene(user_data_profile="edrawings_be_envelope_v1")
assert len(terminal_scene.summary.opaque_user_data) == 2
assert terminal_scene.summary.processed_records == len(new_terminal.summary.records)
assert terminal_scene.summary.placement_status == "unsupported"
assert (
    not terminal_scene.summary.instances
    and not terminal_scene.summary.primitive_instances
)

# Assumed aliases and style links survive a cold, packaged install.
segment_scene = ed.read(
    b";; HSF V19.10 \n(\x13?Style Library/defs){\x13?Style Library/defs\0"
).read_scene()
segment_summary = segment_scene.summary
assert segment_summary.placement_status == "unsupported"
assert segment_summary.processed_records == len(segment_summary.hsf.records)
assert isinstance(segment_summary.segment_aliases[0], ed.SegmentAlias)
assert isinstance(segment_summary.style_segments[0], ed.StyleSegmentReference)
assert segment_summary.style_segments[0].target_id == segment_summary.nodes[-1].id
assert not segment_summary.instances and not segment_summary.references
assert segment_scene.source_bytes(segment_summary.style_segments[0].path.source) == (
    b"?Style Library/defs"
)

# Explicit caller namespace advances parent paths without guessing a default.
parent_path = b"../shared"
context_doc = ed.read(
    b";; HSF V19.10 \n(" + bytes([len(parent_path)]) + parent_path + b")\0"
)
no_context = context_doc.read_scene().summary
assert no_context.import_context is None and no_context.processed_records == 0
with_context = context_doc.read_scene(import_root="/host/import").summary
assert with_context.processed_records == len(with_context.hsf.records)
assert isinstance(with_context.import_context, ed.SceneImportContext)
assert with_context.import_context.resolved_root == "/host/import"
assert with_context.nodes[-1].parent_id == with_context.nodes[1].id
assert all(n.source is None for n in with_context.nodes[:3])
assert with_context.placement_status == "unsupported" and not with_context.instances
assert context_doc.read_scene().summary == no_context
try:
    context_doc.read_scene(mode="strict", import_root="/import")
except ed.UnsupportedFeatureError as err:
    assert err.diagnostic.code == "hsf.import_context"
else:
    raise AssertionError("Strict import context must remain unsupported")

# A supported Style now contributes source-backed display values to placements.
styled_scene = ed.read(
    b";; HSF V19.10 \n(\x04defs~\x01\x01\x02\x03){\x05/defsl" + bytes(24) + b"\0"
).read_scene(mode="strict")
styled_summary = styled_scene.summary
assert styled_summary.status == styled_summary.placement_status == "complete"
assert isinstance(styled_summary.style_resolutions[0], ed.StyleResolution)
assert styled_summary.style_resolutions[0].status == "complete"
styled_color = styled_summary.primitive_instances[0].display.colors[0]
assert styled_color.value == (1, 2, 3)
assert styled_scene.source_bytes(styled_color.source) == b"~\x01\x01\x02\x03"

# Texture requests retain normalized RGB and a bounded Style/image association.
texture_expression = b"diffuse color=`r=0.25 g=0.5 b=1`,diffuse texture=(n)"
texture_scene = ed.read(
    b";; HSF V19.10 \n(\x04defs"
    + b"t\1n\1n\x01\0\x01){\x05/defs"
    + b'"\x01\x01'
    + bytes([len(texture_expression)])
    + texture_expression
    + b"(\x04defs"
    + image_body
    + b")\0"
).read_scene(image_profile="edrawings_1910_u32_v1")
usage = texture_scene.summary.texture_uses[0]
assert isinstance(usage, ed.TextureUse)
assert isinstance(usage.binding, ed.TextureBinding)
assert isinstance(usage.diffuse_color, ed.FloatColorAttribute)
assert usage.diffuse_color.value == (0.25, 0.5, 1.0)
assert texture_scene.source_bytes(usage.texture_name.source) == b"n"
assert usage.binding.status == "complete" and usage.binding.reason is None
assert usage.binding.image_id == texture_scene.summary.images[0].id
assert usage.binding.texture_definition_ids == (texture_scene.summary.textures[0].id,)
assert usage.binding.style_path == (texture_scene.summary.style_segments[0].id,)
assert usage.interpretation_status == "unsupported"
assert (
    not texture_scene.summary.instances
    and not texture_scene.summary.primitive_instances
)

# Matrices inherit as attributes; stored UV bytes stay separate from geometry.
texture_matrix = b"$" + struct.pack("<12f", 2, 0, 0, 0, -3, 0, 0, 0, 1, 5, 7, 0)
parameter_bytes = struct.pack("<6f", -1, 0, 1, 0, 0, 2)
triangle_body = triangle.split(b"\n", 1)[1][:-1]
triangle_body = triangle_body[:1] + b"\x18" + triangle_body[2:]
uv_scene = ed.read(
    b";; HSF V19.10 \n(\x04defs"
    + texture_matrix
    + b"){\x05/defs"
    + triangle_body
    + b"\x1b\x02"
    + parameter_bytes
    + b"\0\0"
).read_scene(mode="strict")
uv_mesh = uv_scene.summary.meshes[0]
assert isinstance(uv_mesh.vertex_parameters, ed.VertexParameters)
assert uv_scene.mesh_buffers(uv_mesh.id).parameters.data == parameter_bytes
assert uv_scene.source_bytes(uv_mesh.vertex_parameters.values_source) == parameter_bytes
assert uv_scene.summary.instances[0].display.texture_matrix.value == (
    2,
    0,
    0,
    0,
    0,
    -3,
    0,
    0,
    0,
    0,
    1,
    0,
    5,
    7,
    0,
    1,
)
texture_options = texture_scene.summary.textures[0].options
assert isinstance(texture_options, ed.TextureOptions)
assert texture_options.enumerations[0].value == "uv"
assert texture_options.decoding_status == "complete"

# Quantized parameters can be bound to a unique Null Shell LOD 0 refinement.
quantized = (
    b"\x03\x01\x02"
    + struct.pack("<4f", 0, 0, 1, 1)
    + b"\x08\x08\0\0\0"
    + bytes.fromhex("ff00ff00 0000ff00")
    + b"\0"
)
quant_doc = ed.read(b";; HSF V19.10 \n" + triangle_body + quantized + b"\0")
quant_scene = quant_doc.read_scene(mode="strict")
quant_mesh = quant_scene.summary.meshes[0]
assert isinstance(quant_mesh.vertex_parameters.quantization, ed.ParameterQuantization)
assert quant_mesh.vertex_parameters.quantization.packing == "le32_msb"
assert quant_scene.mesh_buffers(quant_mesh.id).parameters.data == struct.pack(
    "<6f", 0, 1, 0, 1, 0, 1
)
refined_body = triangle_body[:1] + b"\x08" + bytes(4) + triangle_body[2:]
refined = ed.read(
    b";; HSF V19.10 \nS\x96\x02\0\0q" + refined_body + quantized + b"\0"
).read_scene()
parameter_set = refined.summary.shell_parameter_sets[0]
assert isinstance(parameter_set, ed.ShellParameterSet)
assert parameter_set.target_id == refined.summary.null_shells[0].id
assert parameter_set.association_status == "complete"
assert parameter_set.interpretation_status == "complete"
assert refined.shell_parameters(parameter_set.id).data == struct.pack(
    "<6f", 0, 1, 0, 1, 0, 1
)
assert len(refined.summary.meshes) == len(refined.summary.instances) == 1
refinement_mesh = refined.summary.meshes[0]
assert parameter_set.mesh_id == refinement_mesh.id
assert refined.summary.null_shells[0].mesh_id == refinement_mesh.id
assert isinstance(refinement_mesh.refinement, ed.ShellRefinement)
assert refinement_mesh.refinement.application_status == "complete"
assert refined.mesh_buffers(refinement_mesh.id).parameters == refined.shell_parameters(
    parameter_set.id
)

# Contract 24: quantized local normals and ordered opaque entity strings.
normal_attribute = b"\x01\x01\x08" + struct.pack("<i", 9) + bytes([0, 255, 0]) * 3
entity_attribute = b"\x63U\x03\0x=y\x16\x01\0A\0\0"
normal_scene = ed.read(
    b";; HSF V19.10 \n" + triangle_body + normal_attribute + entity_attribute + b"\0\0"
).read_scene(mode="strict")
normal_mesh = normal_scene.summary.meshes[0]
assert isinstance(normal_mesh.vertex_normals, ed.VertexNormals)
assert normal_mesh.vertex_normals.compression == 1
assert normal_mesh.vertex_normals.packing == "u8_xyz"
assert normal_scene.mesh_buffers(normal_mesh.id).normals.data == struct.pack(
    "<9f", *([-1.0, 1.0, -1.0] * 3)
)
assert normal_scene.source_bytes(normal_mesh.vertex_normals.source) == normal_attribute
assert isinstance(normal_mesh.entity_metadata, ed.EntityMetadata)
assert isinstance(normal_mesh.entity_metadata.fields[0], ed.EntityMetadataField)
assert [f.text.value for f in normal_mesh.entity_metadata.fields] == ["x=y", "A"]
assert normal_mesh.entity_metadata.decoding_status == "complete"
assert normal_mesh.entity_metadata.interpretation_status == "unsupported"
assert normal_scene.summary.placement_status == "complete"

# Contract 25: numeric patterns and marker symbols retain source and inheritance.
pattern_scene = ed.read(
    b";; HSF V19.10 \n-\x02\x21\r\x09\x12@\x09(\x01a"
    + triangle_body[:1]
    + b"\x10"
    + triangle_body[2:]
    + b")\0"
).read_scene(mode="strict")
display = pattern_scene.summary.instances[0].display
assert isinstance(display.line_pattern, ed.LinePatternAttribute)
assert isinstance(display.line_pattern.value, ed.LinePattern)
assert (
    display.line_pattern.value.pattern,
    display.line_pattern.value.cap,
    display.line_pattern.value.join,
) == ("dashed", "round", "bevel")
assert display.edge_pattern.value.pattern == "fine_dotted"
assert isinstance(display.marker_symbol, ed.MarkerSymbolAttribute)
assert isinstance(display.marker_symbol.value, ed.MarkerSymbol)
assert display.marker_symbol.value.symbol == "star"
assert pattern_scene.source_bytes(display.line_pattern.source) == b"-\x02\x21"
assert pattern_scene.source_bytes(display.marker_symbol.source) == b"@\x09"
assert all(
    x.interpretation_status == "complete"
    for x in pattern_scene.summary.rendering_options
)

# Contract 26: forward custom pattern bindings preserve mixed unit operands.
custom_program = b"2 px dash,0.000635 oru blank"
custom_scene = ed.read(
    b";; HSF V19.10 \n-\xff\x06customJ\x06custom"
    + struct.pack("<H", len(custom_program))
    + custom_program
    + triangle_body[:1]
    + b"\x10"
    + triangle_body[2:]
    + b"\0"
).read_scene(mode="strict")
custom_definition = custom_scene.summary.line_styles[0]
assert isinstance(custom_definition.program, ed.LineStyleProgram)
element = custom_definition.program.elements[1]
assert isinstance(element, ed.LineStyleElement)
assert (element.length, element.units, element.kind) == (
    0.000635,
    "object_relative",
    "blank",
)
assert custom_scene.source_bytes(element.length_source) == b"0.000635"
binding = custom_scene.summary.instances[0].display.line_pattern.value.binding
assert isinstance(binding, ed.LineStyleBinding)
assert binding.definition_id == custom_definition.id and binding.status == "complete"
assert custom_scene.summary.rendering_options[0].line_style_binding == binding

# Contract 27: parallel modifiers and an unsized blank are retained separately.
parallel_program = (
    b"1 px dash, parallel, -2 px fixed offset, "
    b"1.5 pixels weight, dash, blank, segmented"
)
parallel_wire = (
    b";; HSF V19.10 \nJ\x06custom"
    + struct.pack("<H", len(parallel_program))
    + parallel_program
    + b"-\xff\x06custom\0"
)
parallel_scene = ed.read(parallel_wire).read_scene(mode="strict")
p = parallel_scene.summary.line_styles[0].program
assert p.kind == "parallel_dash_blank" and not p.elements
assert p.interpretation_status == "complete" and p.reason is None
parallel = p.parallels[1]
assert isinstance(parallel, ed.LineStyleParallel)
assert isinstance(parallel.weight, ed.LineStyleMeasure)
assert parallel.offset.value == -2 and parallel.offset.fixed
assert parallel.weight.value == 1.5 and parallel.weight.units == "pixels"
assert parallel.elements[1].stretchable and parallel.elements[1].length is None
assert parallel_scene.source_bytes(parallel.segmented_source) == b"segmented"
unknown_program = b"1.5 weight, dash, blank, segmented"
unknown_scene = ed.read(
    b";; HSF V19.10 \nJ\x06custom"
    + struct.pack("<H", len(unknown_program))
    + unknown_program
    + b"\0"
).read_scene()
unknown = unknown_scene.summary.line_styles[0].program
assert unknown.parallels[0].weight.units is None
assert unknown.reason == "hsf.line_style_weight_units"
assert unknown_scene.summary.placement_status == "unsupported"

# Contract 28: component-wise text alignment and a forward marker glyph.
glyph_bytes = bytes([10, 0, 0, 2, 246, 0, 10, 0, 0])
glyph_scene = ed.read(
    b";; HSF V19.10 \n*\x25*\x1f@\xff\x06custom"
    + b"j\x06custom"
    + struct.pack("<H", len(glyph_bytes))
    + glyph_bytes
    + b"X"
    + struct.pack("<3f", 1, 2, 3)
    + b"\0"
).read_scene(mode="strict")
glyph_definition = glyph_scene.summary.glyphs[0]
assert isinstance(glyph_definition, ed.GlyphDefinition)
assert isinstance(glyph_definition.program, ed.GlyphProgram)
glyph_command = glyph_definition.program.commands[0]
assert isinstance(glyph_command, ed.GlyphCommand)
assert glyph_command.points == ((-10, 0), (10, 0))
assert glyph_scene.source_bytes(glyph_definition.definition_source) == glyph_bytes
glyph_display = glyph_scene.summary.primitive_instances[0].display
assert isinstance(glyph_display.text_anchor, ed.EnumeratedAttribute)
assert glyph_display.text_anchor.value.name == "center_right"
assert glyph_display.text_justification.value.name == "left"
assert isinstance(glyph_display.marker_symbol.value.binding, ed.GlyphBinding)
assert glyph_display.marker_symbol.value.binding.definition_id == glyph_definition.id
assert glyph_display.marker_symbol.value.symbol == "custom"

# Typed font operands retain stored values without selecting a runtime font.
font_scene = ed.read(
    b";; HSF V19.10 \nF\x0f\x0f\x03ABC"
    + struct.pack("<fBfBB", 2.5, 4, 50, 5, 1)
    + b"\0"
).read_scene()
font_settings = font_scene.summary.rendering_options[0].settings
assert isinstance(font_settings, ed.RenderingSettings)
font_fields = {f.name: f for f in font_settings.operands}
assert isinstance(font_fields["size"], ed.RenderingOperand)
assert font_fields["size"].floats == (2.5,)
assert font_fields["size_units"].enumeration.name == "pixels"
assert font_fields["names"].text.value == "ABC"
assert font_settings.decoding_status == "complete"
assert font_settings.interpretation_status == "unsupported"
unknown_alignment = ed.read(b";; HSF V19.10 \n*\xa5\0").read_scene()
assert unknown_alignment.summary.nodes[0].display.text_justification.value.name is None
assert unknown_alignment.summary.placement_status == "unsupported"

# Contract 29: per-parallel endpoint fitting and explicit pixel scaling requests.
options_program = b"fit = stretch, absolute length, 2 px contrast, 1 px blank"
options_wire = (
    b";; HSF V19.10 \nJ\x06custom"
    + struct.pack("<H", len(options_program))
    + options_program
    + b"-\xff\x06custom\0"
)
options_scene = ed.read(options_wire).read_scene(mode="strict")
options_definition = options_scene.summary.line_styles[0]
options = options_definition.program.parallels[0]
assert options_definition.program.kind == "extended_line_style"
assert isinstance(options.fit, ed.LineStyleFit) and options.fit.mode == "stretch"
assert options_scene.source_bytes(options.fit.value_source) == b"stretch"
assert options_scene.source_bytes(options.absolute_length_source) == b"absolute length"
assert options.absolute_weight_source is None
assert options.elements[0].kind == "contrast" and options.elements[0].length == 2
assert (
    options_scene.summary.rendering_options[0].line_style_binding.status == "complete"
)
transformed_program = b"dash, transformed"
transformed_scene = ed.read(
    b";; HSF V19.10 \nJ\x06custom"
    + struct.pack("<H", len(transformed_program))
    + transformed_program
    + b"\0"
).read_scene()
transformed = transformed_scene.summary.line_styles[0]
assert transformed.reason == "hsf.line_style_geometry_options"
assert transformed.program.reason == transformed.reason
assert (
    transformed_scene.source_bytes(transformed.program.transformed_source)
    == b"transformed"
)
assert transformed_scene.summary.placement_status == "unsupported"

print(
    json.dumps(
        {
            "installed_version": importlib.metadata.version("edrawings-kit"),
            "module": ed.__file__,
            "build_info": info,
            "smoke": "passed",
        },
        indent=2,
    )
)
