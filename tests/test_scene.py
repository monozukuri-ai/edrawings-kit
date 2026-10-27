"""Independent synthetic HSF fixtures; expected geometry is computed in Python."""

import dataclasses
import gc
import json
import math
import struct
import subprocess
import sys
import zlib

import edrawings_kit as ed
import pytest
from edrawings_kit import _core

HEADER = b";; HSF V19.10 \n"
POINTS = (
    (0, 0, 0),
    (2, 0, 0),
    (2, 3, 0),
    (0, 3, 0),
    (0, 0, 4),
    (2, 0, 4),
    (2, 3, 4),
    (0, 3, 4),
)
FACES = (
    4,
    0,
    3,
    2,
    1,
    4,
    4,
    5,
    6,
    7,
    4,
    0,
    1,
    5,
    4,
    4,
    3,
    7,
    6,
    2,
    4,
    0,
    4,
    7,
    3,
    4,
    1,
    2,
    6,
    5,
)


def shell(points=POINTS, faces=FACES, *, bits=8, signed=False, normals=False):
    values = struct.pack(
        f"<{len(faces)}"
        + {
            8: "b" if signed else "B",
            16: "h" if signed else "H",
            32: "i" if signed else "I",
        }[bits],
        *faces,
    )
    result = b"S" + bytes([16 | (128 if signed else 0) | (8 if normals else 0)])
    if signed:
        result += b"\x04\0"
    result += b"\0" + struct.pack("<i", len(points))
    result += b"".join(struct.pack("<3f", *p) for p in points)
    result += b"\x01" + struct.pack("<i", len(values) + 1) + bytes([bits]) + values
    if normals:
        result += b"\x11" + struct.pack("<3f", 0, 0, 1) * len(points) + b"\0"
    return result


def matrix(values):
    return b"%" + struct.pack("<12f", *values)


def assembly():
    return (
        b"(\x04part~\x01\xff\0\0"
        + shell()
        + b"q)q(\x08assembly"
        + matrix((0, 1, 0, -1, 0, 0, 0, 0, 1, 10, 20, 30))
        + b"~\x01\0\0\xffV\x01\0(\x05place"
        + matrix((-1, 0, 0, 0, 1, 0, 0, 0, 1, 2, 0, 0))
        + b"r\0\0\0\0)<\x05/part)"
    )


def unpack(buffer):
    code = {"<f4": "f", "<i4": "i", "<u4": "I"}[buffer.dtype]
    flat = struct.unpack(f"<{len(buffer.data) // 4}{code}", buffer.data)
    if len(buffer.shape) == 2:
        return tuple(zip(*[iter(flat)] * buffer.shape[1], strict=True))
    return flat


@pytest.mark.parametrize("kind", ["raw", "zip", "prefixed"])
@pytest.mark.parametrize("compressed", [False, True])
def test_box_scene_buffers_schema_and_lifetime(kind, compressed, zip_factory, tmp_path):
    body = assembly()
    raw = HEADER + (b"Z" + zlib.compress(body + b"z") if compressed else body) + b"\0"
    data = (
        raw
        if kind == "raw"
        else zip_factory([("eModel", raw)], prefix=kind == "prefixed")
    )
    path = tmp_path / "sample.hsf"
    path.write_bytes(data)
    doc = ed.read_file(path)
    scene = doc.read_scene(mode="strict")
    assert doc.inspection.stages.scene == "not_requested"
    path.unlink()
    del doc
    gc.collect()
    s = scene.summary
    assert s.to_dict() == json.loads(
        _core.read_bytes(data, "{}").read_scene(mode="strict").summary_json()
    )
    assert s.status == s.hsf.stages.scene == s.hsf.stages.hsf_syntax == "complete"
    assert s.units is None and not s.diagnostics
    assert len(s.meshes) == 1 and len(s.instances) == 3 and len(s.references) == 2
    mesh = s.meshes[0]
    assert (mesh.vertex_count, mesh.triangle_count) == (8, 12)
    b = scene.mesh_buffers(mesh.id)
    assert unpack(b.vertices) == POINTS and unpack(b.face_list) == FACES
    assert b.vertices.dtype == "<f4" and b.triangles.dtype == "<u4"
    assert b.vertices.shape == (8, 3) and b.triangles.shape == (12, 3)
    assert b.normals is None
    assert unpack(b.triangle_faces) == tuple(i for i in range(6) for _ in range(2))
    # Independent signed-volume calculation gives 2 * 3 * 4, preserving winding.
    volume = 0.0
    for tri in unpack(b.triangles):
        a, q, c = (POINTS[i] for i in tri)
        cross = (
            q[1] * c[2] - q[2] * c[1],
            q[2] * c[0] - q[0] * c[2],
            q[0] * c[1] - q[1] * c[0],
        )
        volume += sum(a[i] * cross[i] for i in range(3)) / 6
    assert volume == pytest.approx(24)
    placed = s.instances[1]
    assert placed.determinant == -1 and placed.face_color.value == (0, 0, 255)
    assert placed.face_visible.value is False
    for x, y, z in POINTS:
        m = placed.world_transform
        actual = tuple(
            sum((x, y, z, 1)[j] * m[j * 4 + i] for j in range(4)) for i in range(3)
        )
        assert actual == (10 - y, 22 - x, 30 + z)
    assert (
        s.instances[0].face_color.value
        == s.instances[2].face_color.value
        == (255, 0, 0)
    )
    assert s.instances[2].face_visible.value is False
    layout = next(r.shell for r in s.hsf.records if r.shell)
    assert scene.source_bytes(layout.vertices) == b.vertices.data
    assert scene.source_bytes(mesh.source).startswith(b"S")
    with pytest.raises(dataclasses.FrozenInstanceError):
        b.vertices.dtype = "<u4"
    with pytest.raises(ed.InvalidFormatError, match="scene.unknown_mesh"):
        scene.mesh_buffers("missing")
    with pytest.raises(ed.InvalidFormatError, match="hsf.invalid_source_range"):
        scene.source_bytes(ed.HsfSpan("missing", 0, 1))
    del scene
    gc.collect()
    assert unpack(b.vertices) == POINTS


@pytest.mark.parametrize("bits", [8, 16, 32])
@pytest.mark.parametrize("signed", [False, True])
def test_normals_and_face_widths(bits, signed):
    scene = ed.read(
        HEADER + shell(bits=bits, signed=signed, normals=True) + b"\0"
    ).read_scene(mode="strict")
    buffers = scene.mesh_buffers(scene.summary.meshes[0].id)
    assert unpack(buffers.face_list) == FACES
    assert unpack(buffers.normals) == ((0, 0, 1),) * 8


@pytest.mark.parametrize(
    "field",
    [
        "max_hsf_vertices",
        "max_hsf_face_values",
        "max_scene_meshes",
        "max_scene_nodes",
        "max_scene_instances",
        "max_scene_depth",
        "max_scene_visits",
        "max_scene_triangles",
    ],
)
def test_scene_resource_limits_are_structured(field):
    limits = dataclasses.replace(ed.Limits(), **{field: 0})
    with pytest.raises(ed.LimitExceededError) as error:
        ed.read(HEADER + assembly() + b"\0", limits=limits).read_scene()
    assert error.value.diagnostic.entry_id == "raw:0"
    assert error.value.diagnostic.classification == "limit_exceeded"


def test_shared_container_syntax_scene_budget(zip_factory):
    decoded = assembly() + b"z"
    raw = HEADER + b"Z" + zlib.compress(decoded) + b"\0"
    data = zip_factory([("eModel", raw)])
    expected_expanded = len(raw) + len(decoded)
    good = ed.read(data).read_scene(mode="strict")
    usage = good.summary.usage
    assert usage.expanded_bytes == expected_expanded
    assert usage.output_bytes > good.summary.hsf.usage.output_bytes
    exact = dataclasses.replace(
        ed.Limits(),
        max_output_bytes=usage.output_bytes,
        max_expanded_bytes=expected_expanded,
    )
    assert ed.read(data, limits=exact).read_scene(mode="strict").summary.usage == usage
    for limits in [
        dataclasses.replace(exact, max_output_bytes=usage.output_bytes - 1),
        dataclasses.replace(exact, max_expanded_bytes=expected_expanded - 1),
    ]:
        with pytest.raises(ed.LimitExceededError):
            ed.read(data, limits=limits).read_scene()


@pytest.mark.parametrize("mode", ["partial", "strict"])
@pytest.mark.parametrize(
    "body",
    [
        shell(faces=(3, 0, 1, 99)),
        shell(points=((math.nan, 0, 0),) * 8),
        matrix((math.inf,) * 12),
    ],
)
def test_invalid_geometry_never_becomes_partial(body, mode):
    with pytest.raises(ed.InvalidFormatError) as error:
        ed.read(HEADER + body + b"\0").read_scene(mode=mode)
    assert error.value.diagnostic.domain_id == "raw:0/hsf:0"
    assert error.value.diagnostic.hsf_version == "19.10"


def test_holes_unknown_userdata_and_conditions_do_not_claim_complete():
    for body, code in [
        (
            shell(faces=(4, 0, 1, 2, 3, -3, 0, 1, 2), signed=True),
            "hsf.shell_triangulation",
        ),
        (b"[\xff\0S\x10\0", "hsf.unsupported_user_data"),
        (b"<\0\x01a\x01b", "hsf.unresolved_reference"),
    ]:
        doc = ed.read(HEADER + body + b"\0")
        scene = doc.read_scene()
        assert scene.summary.status == scene.summary.hsf.stages.scene == "partial"
        assert scene.summary.diagnostics[0].code == code
        assert all(m.triangle_count == 0 for m in scene.summary.meshes)
        with pytest.raises(ed.UnsupportedFeatureError) as error:
            doc.read_scene(mode="strict")
        assert error.value.diagnostic == scene.summary.diagnostics[0]


def test_entry_selection_ids_and_cli(zip_factory, tmp_path):
    raw = HEADER + shell() + b"\0"
    data = zip_factory([("eModel", raw), ("eModel", raw)])
    doc = ed.read(data)
    with pytest.raises(ed.UnsupportedFeatureError, match="hsf.ambiguous_candidates"):
        doc.read_scene()
    a, b = (doc.read_scene(f"entry:{i}") for i in range(2))
    assert a.summary.meshes[0].id != b.summary.meshes[0].id
    with pytest.raises(ValueError, match="mode"):
        doc.read_scene("entry:0", mode="wrong")
    path = tmp_path / "sample.hsf"
    path.write_bytes(raw)
    args = [sys.executable, "-m", "edrawings_kit", "scene", str(path)]
    run = subprocess.run(
        args + ["--mode", "strict"], capture_output=True, encoding="utf-8", check=True
    )
    assert (
        json.loads(run.stdout)
        == ed.read(raw, read_metadata=False).read_scene(mode="strict").summary.to_dict()
    )
    path.write_bytes(HEADER + b"[\0")
    run = subprocess.run(args, capture_output=True, encoding="utf-8", check=True)
    assert json.loads(run.stdout)["status"] == "partial"
    run = subprocess.run(
        args + ["--mode", "strict"], capture_output=True, encoding="utf-8"
    )
    assert (
        run.returncode == 2
        and json.loads(run.stderr)["error"]["code"] == "hsf.unsupported_user_data"
    )
