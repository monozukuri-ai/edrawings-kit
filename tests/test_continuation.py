"""Contract 10: independent wire fixtures through the installed native binding."""

import gc
import json
import struct
import subprocess
import sys
import zlib

import edrawings_kit as ed
import pytest
from test_scene import unpack
from test_user_data_audit import sample, view
from test_views import PROFILE, compressed, raw


def camera():
    return b">\0" + struct.pack("<11f", 0, 0, 10, 0, 0, 0, 0, 1, 0, 20, 10)


def grid(attributes=False):
    # Three rows, two columns. Mesh has no separate point-count word.
    points = b"".join(struct.pack("<3f", x, y, 0) for y in range(3) for x in range(2))
    body = b"M" + bytes([8 if attributes else 0]) + struct.pack("<ii", 3, 2) + points
    if attributes:
        body += (
            b"\x03\x01\x02"
            + struct.pack("<4f", 0, 0, 1, 1)
            + b"\x08"
            + struct.pack("<i", 12)
            + bytes(range(12))
            + b"\0"
        )
    return body


def texture():
    return b"t\x03tex\x03img" + struct.pack("<H2f", 0x800, 2, 0.5)


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed"])
@pytest.mark.parametrize("compress", [False, True])
def test_grid_camera_sources_buffers_lifetime(wrapper, compress, zip_factory):
    body = b"(\x01a\x01" + camera() + grid() + b"\x01qr\0\0\0\0)"
    data = (
        raw(b"Z" + zlib.compress(body + b"z") + b"\0")
        if compress
        else raw(body + b"\0")
    )
    if wrapper != "raw":
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    del doc
    gc.collect()
    s = scene.summary
    assert s.status == s.placement_status == "complete"
    assert len(s.instances) == 2 and s.references[0].target_id == s.meshes[0].id
    c = s.cameras[0]
    assert isinstance(c, ed.SegmentCamera) and c.node_id == s.nodes[1].id
    assert c.camera.position == (0, 0, 10) and c.camera.field_width == 20
    assert scene.source_bytes(c.camera_source) == camera()[2:]
    assert not s.views and c.status == "complete"
    records = {r.id: r for r in s.hsf.records}
    record = records[c.source_record_id]
    assert isinstance(record.camera, ed.CameraLayout)
    assert record.camera.settings == c.camera_source
    mesh = s.meshes[0]
    assert isinstance(records[mesh.source_record_id].mesh, ed.GridMeshLayout)
    assert mesh.topology == "rectangular_grid"
    buffers = scene.mesh_buffers(mesh.id)
    assert unpack(buffers.vertices) == tuple(
        (x, y, 0) for y in range(3) for x in range(2)
    )
    assert unpack(buffers.triangles) == ((0, 2, 1), (3, 1, 2), (2, 4, 3), (5, 3, 4))
    assert unpack(buffers.triangle_faces) == (0, 1, 2, 3)
    assert unpack(buffers.face_list) == (3, 0, 2, 1, 3, 3, 1, 2, 3, 2, 4, 3, 3, 5, 3, 4)
    assert buffers.normals is None
    assert all(r.source.length == 1 for r in s.hsf.records if r.kind == "pause")


def test_pause_keeps_scope_across_compression_domains():
    data = raw(
        b"Z"
        + zlib.compress(b"(\x01a\x01z")
        + b"Z"
        + zlib.compress(camera() + grid() + b"\x01)z")
        + b"\0"
    )
    s = ed.read(data).read_scene(mode="strict").summary
    assert len(s.hsf.domains) == 3 and len(s.nodes) == 2
    assert s.cameras[0].node_id == s.instances[0].node_id == s.nodes[1].id
    assert s.hsf.unparsed == ()


def test_texture_conditions_index_opaque_and_mesh_parameters_decoded():
    body = (
        texture()
        + b"?\xff\x04\0\0\0flag~\x01\xff\0\0\x08\x01\x07\x09\x02\x01\x02"
        + grid(True)
    )
    doc = ed.read(raw(body + b"\0"))
    hsf = doc.parse_hsf(mode="strict")
    records = hsf.summary.records
    t = records[0].texture
    assert isinstance(t, ed.TextureLayout) and t.flags == 0x800
    assert hsf.source_bytes(t.fields[0].source) == struct.pack("<2f", 2, 0.5)
    assert (
        records[1].kind == "conditions"
        and hsf.source_bytes(records[1].payload) == b"flag"
    )
    assert isinstance(records[4].indexed_color, ed.IndexedColorLayout)
    assert records[4].indexed_color.index == 513
    a = records[5].mesh.attributes[0]
    assert isinstance(a, ed.GridAttributeLayout)
    assert (a.width, a.bits_per_sample) == (2, 8)
    assert hsf.source_bytes(a.values) == bytes(range(12))
    s = doc.read_scene().summary
    assert s.status == "partial" and s.placement_status == "unsupported"
    assert not s.instances and len(s.meshes) == 1
    assert isinstance(s.textures[0], ed.TextureDefinition)
    assert s.textures[0].name.value == "tex" and s.textures[0].image.value == "img"
    assert len(s.rendering_options) == 3
    assert s.nodes[0].face_color is None and s.nodes[0].display.colors[0] is None
    with pytest.raises(ed.UnsupportedFeatureError) as e:
        doc.read_scene(mode="strict")
    assert e.value.diagnostic.code == "hsf.texture_definition"


@pytest.mark.parametrize(
    "record",
    [camera(), texture(), grid(), grid(True), b"?\xfe\x04\0flag", b"\x09\x01\xff\x7f"],
)
def test_truncation_never_becomes_partial_success(record):
    for n in range(len(record)):
        for mode in ("strict", "partial"):
            with pytest.raises(ed.InvalidFormatError):
                ed.read(raw(record[:n])).parse_hsf(mode=mode)


@pytest.mark.parametrize(
    "record,code",
    [
        (b"M\x01", "hsf.mesh_flags"),
        (b">\x80", "hsf.unsupported_camera_projection"),
        (b"t\0\0\0\x80\0\x80", "hsf.texture_flags"),
    ],
)
def test_unknown_profile_preserves_whole_record(record, code):
    doc = ed.read(raw(record + b"h\x01\0"))
    h = doc.parse_hsf().summary
    assert not h.records and h.diagnostics[0].code == code
    assert h.domains[0].parsed_bytes == h.header.byte_len
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.parse_hsf(mode="strict")


@pytest.mark.parametrize(
    "body,limits,code",
    [
        (grid(), {"max_hsf_vertices": 5}, "hsf.limit_vertices"),
        (grid(), {"max_hsf_face_values": 15}, "hsf.limit_face_values"),
        (grid(), {"max_scene_triangles": 3}, "hsf.limit_triangles"),
        (view() + camera(), {"max_scene_views": 1}, "hsf.limit_views"),
        (texture(), {"max_scene_definitions": 0}, "hsf.limit_definitions"),
    ],
)
def test_shared_cumulative_limits(body, limits, code):
    with pytest.raises(ed.LimitExceededError) as e:
        ed.read(raw(body + b"\0"), limits=ed.Limits(**limits)).read_scene()
    assert e.value.diagnostic.code == code


def test_user_data_remains_opt_in_and_withholds_placements(tmp_path):
    data = compressed(sample() + b"h\x01\x01" + camera() + grid() + b"z")
    doc = ed.read(data)
    assert not doc.read_scene().summary.meshes
    scene = doc.read_scene(user_data_profile=PROFILE)
    assert len(scene.summary.meshes) == len(scene.summary.cameras) == 1
    assert (
        scene.summary.placement_status == "unsupported" and not scene.summary.instances
    )
    path = tmp_path / "continuation.hsf"
    path.write_bytes(data)
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "edrawings_kit",
            "scene",
            str(path),
            "--user-data-profile",
            PROFILE,
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    result = json.loads(run.stdout)
    assert result["cameras"] == scene.summary.to_dict()["cameras"]
    assert result["meshes"] == scene.summary.to_dict()["meshes"]
