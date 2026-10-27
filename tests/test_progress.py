"""Independent fixtures for the next geometry and render-setting boundaries."""

import gc
import struct
import zlib

import edrawings_kit as ed
import pytest
from test_scene import unpack
from test_views import raw


def batch(flags=0x1000, lengths=(2, 3)):
    n = sum(lengths)
    data = bytes([16]) + struct.pack("<Hi", flags, n)
    if flags & 2:
        data += struct.pack("<i", len(lengths))
    data += struct.pack(f"<{len(lengths)}i", *lengths)
    return data + b"".join(
        struct.pack("<f", i * 3 + axis)
        for i in range(n)
        for axis in range(3)
        if not flags & (0x100 << (axis * 2))
    )


def shell(refinement=True):
    b = b"S" + bytes([10 if refinement else 26])
    if refinement:
        b += struct.pack("<I", 123)
    b += b"\0" + struct.pack("<i9f", 3, 0, 0, 0, 1, 0, 0, 0, 1, 0)
    b += b"\x01\x05\0\0\0\x08\x03\0\x01\x02"
    b += b"\x01\x07\x0c" + struct.pack("<i", 12) + bytes(12)
    b += (
        b"\x03\x01\x01"
        + struct.pack("<2f", 0, 1)
        + b"\x08"
        + struct.pack("<i", 4)
        + bytes([10, 20, 30, 0])
    )
    return b + b"\x63U\x03\0x=y\x16\x01\0A\0\0\0"


def rendering(weight=-1.0):
    # All hidden-line payload fields, including the weight's -1 sentinel.
    hlr = bytes([0x9C, 0x80, 0x13, 0])
    hlr += struct.pack("<i6f", 17, 0.5, 2, 0.1, 0.2, 0.3, weight)
    if weight != -1:
        hlr += b"\x04"
    hlr += b"\x02"
    # Shadow flag order is plane, light, color, blur, resolution, opacity.
    shadow = b"\xff\x03" + struct.pack("<7f", 0, 1, 0, 2, 0, -1, 0)
    shadow += b"\x01\x02\x03\x05" + struct.pack("<Hf", 512, 0.25)
    return (
        b"R"
        + struct.pack("<4I", 0x81000000, 0x110, 0x01000000, 0x110)
        + hlr
        + struct.pack("<2f", 0, 0.1)
        + shadow
    )


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed"])
@pytest.mark.parametrize("compressed", [False, True])
def test_marker_batch_buffers_scope_and_group_reference(
    wrapper, compressed, zip_factory
):
    body = b"(\x01aX" + struct.pack("<3f", 1, 2, 3) + batch() + b"qr\0\0\0\0)"
    hsf = (
        raw(b"Z" + zlib.compress(body + b"z") + b"\0")
        if compressed
        else raw(body + b"\0")
    )
    data = (
        hsf
        if wrapper == "raw"
        else zip_factory([("eModel", hsf)], prefix=wrapper == "prefixed")
    )
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    del doc
    gc.collect()
    s = scene.summary
    assert s.status == s.placement_status == "complete"
    marker, poly = s.primitives
    assert marker.kind == "marker" and marker.part_lengths == ()
    assert unpack(scene.primitive_points(marker.id)) == ((1, 2, 3),)
    assert poly.kind == "poly_polyline" and poly.part_lengths == (2, 3)
    assert unpack(scene.primitive_points(poly.id)) == tuple(
        (i * 3, i * 3 + 1, 0) for i in range(5)
    )
    record = next(r for r in s.hsf.records if r.poly_polyline)
    layout = record.poly_polyline
    assert isinstance(layout, ed.PolyPolylineLayout)
    assert (layout.point_count, layout.primitive_count, layout.dimensions) == (5, 2, 2)
    assert scene.source_bytes(layout.lengths) == struct.pack("<2i", 2, 3)
    assert layout.points == poly.points_source and layout.points.length == 40
    assert s.references[0].target_id == poly.id and len(s.primitive_instances) == 3


@pytest.mark.parametrize("flags", [0, 2, 0x100, 0x400, 0x1402])
def test_batch_dimensional_reconstruction(flags):
    scene = ed.read(raw(batch(flags) + b"\0")).read_scene(mode="strict")
    p = scene.summary.primitives[0]
    points = unpack(scene.primitive_points(p.id))
    assert points == tuple(
        tuple(0 if flags & (0x100 << (axis * 2)) else i * 3 + axis for axis in range(3))
        for i in range(5)
    )


def test_shell_attributes_are_source_backed_and_refinements_stay_unplaced():
    doc = ed.read(raw(shell() + b"\0"))
    hsf = doc.parse_hsf(mode="strict")
    s = hsf.summary.records[0].shell
    assert s.flags == 10 and s.refinement_index == 123
    assert s.normals is None and len(s.attributes) == 3
    assert isinstance(s.attributes[0], ed.ShellAttributeLayout)
    assert hsf.source_bytes(s.attributes[0].fields[-1].source) == bytes(12)
    assert hsf.source_bytes(s.attributes[1].fields[-1].source) == bytes([10, 20, 30, 0])
    assert hsf.source_bytes(s.attributes[2].fields[0].source) == b"x=y"
    assert hsf.source_bytes(s.attributes[2].fields[1].source) == b"A\0"
    assert not doc.read_scene().summary.meshes
    with pytest.raises(ed.UnsupportedFeatureError) as e:
        doc.read_scene(mode="strict")
    assert e.value.diagnostic.code == "hsf.shell_lod"
    scene = ed.read(raw(shell(False) + b"\0")).read_scene()
    assert unpack(scene.mesh_buffers(scene.summary.meshes[0].id).triangles) == (
        (0, 1, 2),
    )
    assert (
        scene.summary.placement_status == "complete"
        and len(scene.summary.instances) == 1
    )


@pytest.mark.parametrize("weight", [-1.0, 0.0, -2.0, 3.0])
def test_hidden_line_shadow_field_order_units_and_texture_matrix(weight):
    matrix = b"$" + struct.pack("<12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, 2, 3, 4)
    doc = ed.read(raw(rendering(weight) + matrix + b"\0"))
    hsf = doc.parse_hsf(mode="strict")
    fields = {f.name: f for f in hsf.summary.records[0].rendering.fields}
    assert ("hidden_line_weight_units" in fields) == (weight != -1)
    assert struct.unpack(
        "<3f", hsf.source_bytes(fields["hidden_line_color"].source)
    ) == pytest.approx((0.1, 0.2, 0.3))
    assert hsf.source_bytes(fields["shadow_color"].source) == b"\x01\x02\x03"
    assert hsf.source_bytes(fields["shadow_resolution"].source) == struct.pack(
        "<H", 512
    )
    assert hsf.summary.records[1].kind == "texture_matrix"
    scene = doc.read_scene().summary
    assert len(scene.rendering_options) == 2 and scene.nodes[0].local_transform is None
    assert scene.placement_status == "unsupported"
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.read_scene(mode="strict")


@pytest.mark.parametrize(
    "record",
    [
        batch(),
        batch(2),
        shell(),
        rendering(3),
        b"$" + struct.pack("<12f", *range(12)),
        b"X" + struct.pack("<3f", 1, 2, 3),
    ],
)
def test_each_truncation_is_invalid(record):
    for n in range(len(record)):
        for mode in ("strict", "partial"):
            with pytest.raises(ed.InvalidFormatError):
                ed.read(raw(record[:n])).parse_hsf(mode=mode)


def test_limits_and_unknown_batch_profiles():
    with pytest.raises(ed.LimitExceededError):
        ed.read(
            raw(batch() + batch() + b"\0"), limits=ed.Limits(max_scene_primitives=3)
        ).read_scene()
    with pytest.raises(ed.LimitExceededError):
        ed.read(raw(batch() + b"\0"), limits=ed.Limits(max_hsf_vertices=4)).parse_hsf()
    for flags in [1, 4, 0x4000, 0x1500, 0x8000]:
        h = (
            ed.read(raw(b"\x10" + struct.pack("<H", flags) + b"h\x01\0"))
            .parse_hsf()
            .summary
        )
        assert not h.records and h.domains[0].parsed_bytes == h.header.byte_len
    bad = b"$" + struct.pack("<12f", float("inf"), *range(11)) + b"\0"
    with pytest.raises(ed.InvalidFormatError):
        ed.read(raw(bad)).parse_hsf()


def test_non_xyz_mesh_parameter_packing_pads_to_a_word():
    # 3x3 grid, width 1, eight bits => 9 meaningful octets in 12 stored bytes.
    wire = b"M\x08" + struct.pack("<ii", 3, 3) + bytes(9 * 12)
    wire += (
        b"\x03\x01\x01"
        + struct.pack("<2f", 0, 1)
        + b"\x08"
        + struct.pack("<i", 12)
        + bytes(12)
        + b"\0\0"
    )
    h = ed.read(raw(wire)).parse_hsf(mode="strict")
    assert h.summary.records[0].mesh.attributes[0].values.length == 12
    bad = wire[:-18] + struct.pack("<i", 9) + bytes(9) + b"\0\0"
    with pytest.raises(ed.InvalidFormatError):
        ed.read(raw(bad)).parse_hsf()
