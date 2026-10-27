"""Null Shell updates preserve source geometry and the original segment."""

import gc
import json
import struct
import subprocess
import sys

import edrawings_kit as ed
import pytest
from test_quantized_parameters import quantized
from test_rendering import NULL
from test_scene import shell, unpack
from test_style_resolution import opened
from test_texture_mapping import raw_parameters
from test_views import compressed, raw


def refined(body, index=0, lod=0):
    offset = 4 if body[1] & 128 else 2
    return (
        body[:1]
        + bytes([body[1] & ~16])
        + body[2:offset]
        + struct.pack("<I", index)
        + bytes([lod])
        + body[offset + 1 :]
    )


def translate(x):
    return b"%" + struct.pack("<12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, x, 0, 0)


@pytest.mark.parametrize("bits", [8, 16, 32])
@pytest.mark.parametrize("signed", [False, True])
@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed", "compressed"])
def test_refinement_buffers_and_owner_survive_wrappers(
    bits, signed, wrapper, zip_factory
):
    body = shell(bits=bits, signed=signed, normals=True)
    wire = opened(b"original") + translate(10) + b"~\x01\x01\x02\x03" + NULL + b"q)"
    wire += (
        opened(b"arrival")
        + translate(100)
        + b"~\x01\x07\x08\x09"
        + refined(body)
        + b")"
    )
    wire += b"r\0\0\0\0<\x09/original"
    data = compressed(wire + b"z") if wrapper == "compressed" else raw(wire + b"\0")
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    del doc
    gc.collect()
    s = scene.summary
    assert s.status == s.placement_status == "complete"
    m = s.meshes[0]
    info = m.refinement
    assert isinstance(info, ed.ShellRefinement)
    assert info.target_id == s.null_shells[0].id and s.null_shells[0].mesh_id == m.id
    assert (
        info.target_node_id == s.nodes[1].id and info.context_node_id == s.nodes[2].id
    )
    assert m.owner_node_id == info.target_node_id != info.context_node_id
    assert info.application_status == info.attribute_status == "complete"
    assert info.application_reason is None and info.lod == info.index == 0
    full = ed.read(raw(body + b"\0")).read_scene(mode="strict")
    assert scene.mesh_buffers(m.id) == full.mesh_buffers(full.summary.meshes[0].id)
    assert scene.source_bytes(m.source) == refined(body)
    assert len(s.instances) == 3
    assert [i.world_transform[12] for i in s.instances] == [10, 0, 10]
    assert all(i.node_id != s.nodes[2].id for i in s.instances)
    assert [i.face_color.value for i in s.instances if i.face_color] == [(1, 2, 3)] * 2
    assert s.references[0].target_id == s.null_shells[0].id


@pytest.mark.parametrize("parameters", ["raw", "quantized"])
def test_parameters_bind_to_exact_refinement_vertex_order(parameters):
    body = raw_parameters("shell")[0] if parameters == "raw" else quantized()[0]
    scene = ed.read(raw(NULL + b"q" + refined(body) + b"\0")).read_scene(mode="strict")
    s = scene.summary
    p = s.shell_parameter_sets[0]
    m = s.meshes[0]
    assert p.mesh_id == m.id and p.interpretation_status == "complete"
    assert scene.shell_parameters(p.id) == scene.mesh_buffers(m.id).parameters
    assert p.vertex_parameters == m.vertex_parameters
    assert len(s.instances) == 1 and s.instances[0].mesh_id == m.id


def test_reference_before_refinement_and_tag_alias_after_refinement():
    body = refined(shell())
    s = (
        ed.read(raw(NULL + b"qr\0\0\0\0" + body + b"qr\x01\0\0\0\0"))
        .read_scene(mode="strict")
        .summary
    )
    assert len(s.instances) == 3
    assert all(r.target_id == s.null_shells[0].id for r in s.references)
    # A duplicate through an alias must revoke the same object binding.
    s = (
        ed.read(raw(NULL + b"q" + body + b"q" + refined(shell(), 1) + b"\0"))
        .read_scene()
        .summary
    )
    assert len(s.meshes) == 1 and s.null_shells[0].mesh_id is None
    assert s.meshes[0].refinement.application_reason == "hsf.refinement_duplicate"
    assert not s.instances and s.placement_status == "unsupported"


@pytest.mark.parametrize("tail", [refined(shell()), refined(quantized()[0])])
def test_duplicates_revoke_binding_and_never_choose_last(tail):
    first = refined(quantized()[0])
    wire = NULL + b"q" + first + tail + tail + b"l" + bytes(24)
    doc = ed.read(raw(wire + b"\0"))
    s = doc.read_scene().summary
    assert len(s.meshes) == 1 and s.null_shells[0].mesh_id is None
    assert s.meshes[0].refinement.application_status == "unsupported"
    assert s.shell_parameter_sets[0].interpretation_status == "unsupported"
    assert all(x.mesh_id is None for x in s.shell_parameter_sets[1:])
    assert not s.instances and not s.primitive_instances
    with pytest.raises(ed.UnsupportedFeatureError) as error:
        doc.read_scene(mode="strict")
    assert error.value.diagnostic.code == "hsf.refinement_duplicate"


@pytest.mark.parametrize(
    "prefix,lod",
    [
        (b"", 0),
        (shell() + b"q", 0),
        (b"X" + bytes(12) + b"q", 0),
        (NULL + b"q", 1),
        (NULL[:-1] + b"\x01q", 0),
    ],
)
def test_unsupported_target_or_lod_never_creates_geometry(prefix, lod):
    doc = ed.read(raw(prefix + refined(shell(), lod=lod) + b"l" + bytes(24) + b"\0"))
    s = doc.read_scene().summary
    assert not any(m.refinement for m in s.meshes)
    assert not s.instances and not s.primitive_instances
    with pytest.raises(ed.UnsupportedFeatureError) as error:
        doc.read_scene(mode="strict")
    assert error.value.diagnostic.code == "hsf.shell_lod"


def test_known_normals_and_metadata_keep_geometry_and_allow_placements():
    body = shell()
    body = body[:1] + b"\x18" + body[2:]
    attrs = b"\x01\x07\x0c" + struct.pack("<i", 24) + bytes(24) + b"\x63U\x03\0x=y\0\0"
    doc = ed.read(raw(NULL + b"q" + refined(body + attrs) + b"\0"))
    scene = doc.read_scene()
    m = scene.summary.meshes[0]
    assert m.refinement.application_status == "complete"
    assert m.refinement.attribute_status == "complete"
    assert m.normal_count == 8 and scene.mesh_buffers(m.id).normals is not None
    assert m.triangle_count == 12 and len(scene.summary.instances) == 1
    assert not scene.summary.rendering_options
    assert m.entity_metadata.fields[0].text.value == "x=y"
    assert doc.read_scene(mode="strict").summary.status == "complete"


def test_strip_fan_connectivity_and_polygon_triangulation_boundary():
    base = shell(faces=(4, 0, 1, 2, 3, -4, 4, 5, 6, 7), signed=True)
    base = base[:1] + bytes([base[1] | 4]) + base[2:]
    scene = ed.read(raw(NULL + b"q" + refined(base) + b"\0")).read_scene(mode="strict")
    m = scene.summary.meshes[0]
    b = scene.mesh_buffers(m.id)
    assert unpack(b.triangles) == ((0, 1, 2), (2, 1, 3), (4, 5, 6), (4, 6, 7))
    assert unpack(b.triangle_faces) == (0, 0, 1, 1)
    body = refined(shell(faces=(5, 0, 1, 2, 3, 4)))
    doc = ed.read(raw(NULL + b"q" + body + b"\0"))
    m = doc.read_scene().summary.meshes[0]
    assert m.triangle_count == 0 and m.triangulation == "partial"
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.read_scene(mode="strict")


@pytest.mark.parametrize("faces", [(3, 0, 1, 100), (4, 0, 1, 2), (2, 0, 1)])
def test_invalid_connectivity_is_not_partial_success(faces):
    doc = ed.read(raw(NULL + b"q" + refined(shell(faces=faces)) + b"\0"))
    for mode in ("partial", "strict"):
        with pytest.raises(ed.InvalidFormatError):
            doc.read_scene(mode=mode)


@pytest.mark.parametrize(
    "limits",
    [
        ed.Limits(max_scene_triangles=11),
        ed.Limits(max_scene_meshes=1),
        ed.Limits(max_output_bytes=1000),
    ],
)
def test_refinement_geometry_charges_shared_limits(limits):
    doc = ed.read(raw(NULL + b"q" + refined(shell()) + b"\0"), limits=limits)
    with pytest.raises(ed.LimitExceededError):
        doc.read_scene()


def test_ordinary_mesh_ids_preserved_and_cli_drawing_contract(tmp_path):
    wire = NULL + b"q" + refined(shell()) + shell() + b"\0"
    doc = ed.read(raw(wire))
    s = doc.read_scene(mode="strict").summary
    assert s.meshes[0].id.endswith("refinement_mesh:0") and s.meshes[1].id.endswith(
        "mesh:0"
    )
    assert s.meshes[1].refinement is None
    d = doc.read_drawing().summary
    assert d.scene.meshes == s.meshes and d.assessment.status == "partial"
    path = tmp_path / "refinement.hsf"
    path.write_bytes(raw(wire))
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path), "--mode", "strict"],
        capture_output=True,
        encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["meshes"] == [m.to_dict() for m in s.meshes]
