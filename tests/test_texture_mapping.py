"""Stored parameters and texture-matrix inheritance, independent wire expectations."""

import gc
import json
import struct
import subprocess
import sys
from dataclasses import FrozenInstanceError

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_scene import shell, unpack
from test_style_resolution import opened, styled
from test_views import compressed, raw


def matrix(sx=2, sy=-3, tx=5, ty=7):
    return b"$" + struct.pack("<12f", sx, 0, 0, 0, sy, 0, 0, 0, 1, tx, ty, 0)


def raw_parameters(kind="mesh", width=2):
    # Negative and >1 values are legitimate coordinates; never clamp or flip V.
    count = 6 if kind == "mesh" else 8
    values = tuple(
        tuple((i - 2) * (axis + 1) / 4 for axis in range(width)) for i in range(count)
    )
    data = b"".join(struct.pack(f"<{width}f", *v) for v in values)
    if kind == "mesh":
        body = grid()
        body = body[:1] + b"\x08" + body[2:]
    else:
        # Keep independently stored normals as well as parameters.
        body = shell(normals=True)[:-1]
    return body + b"\x1b" + bytes([width]) + data + b"\0", values, data


def read(body, **kwargs):
    return ed.read(raw(body + b"\0"), **kwargs).read_scene(mode="strict")


@pytest.mark.parametrize("kind", ["mesh", "shell"])
@pytest.mark.parametrize("width", [1, 2, 3, 4, 5, 128])
@pytest.mark.parametrize("version", ["8.05", "14.50", "19.10"])
def test_stored_parameters_exact_buffer_and_source(kind, width, version):
    body, values, expected = raw_parameters(kind, width)
    scene = ed.read(
        f";; HSF V{version} \n".encode() + matrix() + body + b"\0"
    ).read_scene(mode="strict")
    mesh = scene.summary.meshes[0]
    p = mesh.vertex_parameters
    assert isinstance(p, ed.VertexParameters) and (p.width, p.count) == (
        width,
        len(values),
    )
    b = scene.mesh_buffers(mesh.id)
    assert p.quantization is None
    assert b.parameters.dtype == "<f4" and b.parameters.shape == (len(values), width)
    assert unpack(b.parameters) == values and b.parameters.data == expected
    assert scene.source_bytes(p.values_source) == expected
    assert scene.source_bytes(p.source) == b"\x1b" + bytes([width]) + expected
    assert scene.summary.instances[0].display.texture_matrix.value == (
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
    assert (
        scene.summary.status == "complete"
        and scene.summary.placement_status == "complete"
    )
    if kind == "shell":
        assert unpack(b.normals) == ((0, 0, 1),) * 8
    with pytest.raises(FrozenInstanceError):
        p.width = 9


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed", "compressed"])
def test_wrappers_lifetime_and_nested_style_matrix(wrapper, zip_factory):
    body, _, expected = raw_parameters()
    payload = (
        opened(b"base")
        + matrix()
        + b")"
        + opened(b"defs")
        + styled(b"/base")
        + b")"
        + styled(b"/defs")
        + body
    )
    data = (
        compressed(payload + b"z") if wrapper == "compressed" else raw(payload + b"\0")
    )
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    del doc
    gc.collect()
    m = scene.summary.meshes[0]
    assert scene.mesh_buffers(m.id).parameters.data == expected
    assert all(x.status == "complete" for x in scene.summary.style_resolutions)
    a = scene.summary.instances[0].display.texture_matrix
    assert scene.source_bytes(a.source) == matrix()
    assert scene.summary.nodes[0].display.texture_matrix is None
    assert scene.summary.rendering_options[0].interpretation_status == "complete"


def test_local_set_replaces_parent_and_style_without_concatenation():
    scene = read(
        matrix(10, 20)
        + opened(b"defs")
        + matrix(30, 40)
        + b")"
        + opened(b"part")
        + styled(b"/defs")
        + matrix(50, 60)
        + matrix(2, 3, 11, 13)
        + grid()
        + b")"
    )
    a = scene.summary.instances[0].display.texture_matrix
    assert a.value == (2, 0, 0, 0, 0, 3, 0, 0, 0, 0, 1, 0, 11, 13, 0, 1)
    assert scene.source_bytes(a.source) == matrix(2, 3, 11, 13)
    assert scene.summary.instances[0].world_transform == (
        1,
        0,
        0,
        0,
        0,
        1,
        0,
        0,
        0,
        0,
        1,
        0,
        0,
        0,
        0,
        1,
    )


def test_matrix_inherits_from_include_instance_parent_and_not_style_parent():
    body = opened(b"defs") + matrix(90, 90) + opened(b"empty") + b"))"
    body += opened(b"part") + styled(b"/defs/empty") + grid() + b")"
    body += opened(b"left") + matrix(2, 3) + b"<\x05/part)"
    body += opened(b"right") + matrix(5, 6) + b"<\x05/part)"
    s = read(body).summary
    assert [
        None if i.display.texture_matrix is None else i.display.texture_matrix.value[0]
        for i in s.instances
    ] == [None, 2, 5]


@pytest.mark.parametrize(
    "tail,code",
    [
        (styled(b"/"), "hsf.style_cycle"),
        (styled(b"/missing"), "hsf.style_unresolved"),
        (b"{\0\x05/defs\0", "hsf.style_condition"),
    ],
)
def test_unknown_style_semantics_keep_placements_withheld(tail, code):
    body = opened(b"defs") + matrix() + b")" + tail + grid()
    s = ed.read(raw(body + b"\0")).read_scene().summary
    assert s.style_resolutions[0].reason == code and not s.instances
    with pytest.raises(ed.UnsupportedFeatureError):
        read(body)


def test_overlapping_style_matrices_and_incomplete_scene_remain_unsupported():
    body = (
        opened(b"a")
        + matrix()
        + b")"
        + opened(b"b")
        + matrix()
        + b")"
        + styled(b"/a")
        + styled(b"/b")
        + grid()
    )
    s = ed.read(raw(body + b"\0")).read_scene().summary
    assert s.style_resolutions[0].reason == "hsf.style_conflict" and not s.instances
    partial = (
        ed.read(
            raw(
                matrix()
                + opened(b"empty")
                + b")"
                + styled(b"/empty")
                + grid()
                + b"\xff\0"
            )
        )
        .read_scene()
        .summary
    )
    assert not partial.instances and partial.nodes[0].display.texture_matrix is not None


def test_quantized_parameters_decoded_and_refinements_not_promoted():
    s = ed.read(raw(grid(True) + b"\0")).read_scene(mode="strict")
    m = s.summary.meshes[0]
    assert m.vertex_parameters.quantization.packing == "le32_msb"
    assert s.mesh_buffers(m.id).parameters.shape == (6, 2)
    assert len(s.summary.instances) == 1
    body, _, _ = raw_parameters("shell")
    # Turn the full-resolution definition into a refinement with an explicit key.
    body = body[:1] + b"\x0a" + struct.pack("<I", 0) + body[2:]
    s = ed.read(raw(body + b"\0")).read_scene().summary
    assert not s.meshes and s.diagnostics[0].code == "hsf.shell_lod"
    assert len(s.shell_parameter_sets) == 1
    assert (
        s.shell_parameter_sets[0].association_reason
        == "hsf.parameter_target_unresolved"
    )


@pytest.mark.parametrize("which", ["matrix", "parameters"])
def test_nonfinite_truncated_and_resource_limits(which):
    body, _, _ = raw_parameters()
    if which == "matrix":
        bad = matrix(float("nan")) + grid()
        cut = matrix()[:-1]
    else:
        bad = body[:-5] + struct.pack("<f", float("inf")) + b"\0"
        cut = body[:-5]
    with pytest.raises(ed.InvalidFormatError):
        read(bad)
    with pytest.raises(ed.InvalidFormatError):
        read(cut)
    with pytest.raises(ed.LimitExceededError):
        read(matrix() + body, limits=ed.Limits(max_output_bytes=1000))


def option_texture(flags, fields=b""):
    bits = struct.pack("<I", flags) if flags & 0x8000 else struct.pack("<H", flags)
    return b"t\x03tex\x03img" + bits + fields


@pytest.mark.parametrize(
    "bit,raw_value,name,value",
    [
        (1, 1, "parameter_source", "uv"),
        (2, 3, "tiling", "mirror"),
        (4, 2, "interpolation", "trilinear"),
        (8, 3, "decimation", "mipmap"),
        (16, 6, "red_mapping", "luminance"),
        (32, 0, "green_mapping", "red"),
        (64, 7, "blue_mapping", "none"),
        (128, 5, "alpha_mapping", "one"),
        (256, 2, "parameter_function", "cylinder"),
        (512, 3, "layout", "cubic_faces"),
    ],
)
def test_documented_option_enumerations_preserve_raw_and_source(
    bit, raw_value, name, value
):
    scene = ed.read(raw(option_texture(bit, bytes([raw_value])) + b"\0")).read_scene()
    t = scene.summary.textures[0]
    e = t.options.enumerations[0]
    assert isinstance(t.options, ed.TextureOptions) and isinstance(e, ed.TextureEnum)
    assert (e.name, e.raw, e.value) == (name, raw_value, value)
    assert scene.source_bytes(e.source) == bytes([raw_value])
    assert (
        t.options.decoding_status == "complete"
        and t.interpretation_status == "unsupported"
    )
    assert not scene.summary.instances


def test_option_absence_unknowns_and_extension_bits_not_guessed():
    body = (
        option_texture(0)
        + option_texture(1, b"\xff")
        + option_texture(0x28001, b"\x01\x01")
    )
    s = ed.read(raw(body + b"\0")).read_scene().summary
    assert not s.textures[0].options.enumerations
    assert s.textures[1].options.enumerations[0].value is None
    assert s.textures[1].options.decoding_status == "unsupported"
    opt = s.textures[2].options
    assert opt.enumerations[0].value == "uv" and opt.enumerations[1].value is None
    assert opt.enumerations[1].raw == 1 and opt.unevaluated_flags == 0x20000
    assert opt.decoding_status == "unsupported"


def test_scale_transform_and_offset_sources_and_cli(tmp_path):
    body = option_texture(0x48C00, struct.pack("<2f", 2, -0.5) + b"\x04/a/b\x02")
    scene = ed.read(raw(body + b"\0")).read_scene()
    opt = scene.summary.textures[0].options
    assert isinstance(
        opt.value_scale, ed.FloatPairAttribute
    ) and opt.value_scale.value == (2, -0.5)
    assert opt.transform_segment.value == "/a/b" and opt.parameter_offset.value == 2
    assert opt.decoding_status == "complete"
    assert scene.source_bytes(opt.parameter_offset.source) == b"\x02"
    path = tmp_path / "test.hsf"
    path.write_bytes(raw(body + b"\0"))
    result = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path)],
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["textures"][0]["options"] == opt.to_dict()
