"""Normals use an independent bit-string writer and explicit polar axis formula."""

import gc
import math
import struct
from dataclasses import FrozenInstanceError

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_quantized_parameters import packed_codes
from test_rendering import NULL
from test_scene import shell
from test_shell_refinement import refined
from test_views import compressed, raw


def f32(x):
    return struct.unpack("<f", struct.pack("<f", x))[0]


def normal_shell(scheme=7, bits=12, codes=None, pad=0, count=3):
    width = 2 if scheme == 7 else 3
    top = (1 << bits) - 1
    codes = (
        codes
        if codes is not None
        else ([0, top, top // 2, top // 3, 1, top - 1] * width)[: count * width]
    )
    packed = packed_codes(codes, width, bits, pad)
    attr = bytes([1, scheme, bits]) + struct.pack("<i", len(packed)) + packed
    base = shell(
        points=((0, 0, 0), (1, 0, 0), (0, 1, 0)) if count else (),
        faces=(3, 0, 1, 2) if count else (),
    )
    return base[:1] + b"\x18" + base[2:] + attr + b"\0", attr, packed, codes


def expected_normals(scheme, bits, codes):
    bounds = (
        [(-f32(math.pi), f32(math.pi)), (0.0, f32(math.pi))]
        if scheme == 7
        else [(-1.0, 1.0)] * 3
    )
    maximum = (1 << bits) - 1
    values = [
        f32(
            bounds[i % len(bounds)][0]
            + (bounds[i % len(bounds)][1] - bounds[i % len(bounds)][0]) * (v / maximum)
        )
        for i, v in enumerate(codes)
    ]
    if scheme == 7:
        result = []
        for theta, phi in zip(values[::2], values[1::2], strict=True):
            result += [
                f32(math.sin(phi) * math.cos(theta)),
                f32(math.cos(phi)),
                f32(math.sin(phi) * math.sin(theta)),
            ]
        return result
    return values


@pytest.mark.parametrize("scheme", [1, 7])
@pytest.mark.parametrize("bits", [2, 7, 8, 9, 12, 16, 24, 31])
@pytest.mark.parametrize("version", ["8.05", "14.50", "19.10"])
def test_quantized_normals_across_words_and_versions(scheme, bits, version):
    body, attr, packed, codes = normal_shell(scheme, bits, pad=1)
    scene = ed.read(f";; HSF V{version} \n".encode() + body + b"\0").read_scene(
        mode="strict"
    )
    m = scene.summary.meshes[0]
    n = m.vertex_normals
    assert isinstance(n, ed.VertexNormals)
    assert (
        n.count == m.normal_count == 3
        and n.compression == scheme
        and n.bits_per_sample == bits
    )
    assert n.encoding == ("quantized_polar" if scheme == 7 else "quantized_xyz")
    assert n.packing == ("u8_xyz" if (scheme, bits) == (1, 8) else "le32_msb")
    assert tuple(tuple(f32(v) for v in b) for b in n.bounds) == (
        ((-f32(math.pi), f32(math.pi)), (0.0, f32(math.pi)))
        if scheme == 7
        else ((-1.0, 1.0),) * 3
    )
    assert (
        scene.source_bytes(n.source) == attr
        and scene.source_bytes(n.values_source) == packed
    )
    expected = expected_normals(scheme, bits, codes)
    buf = scene.mesh_buffers(m.id).normals
    assert buf.shape == (3, 3) and buf.dtype == "<f4"
    assert buf.data == struct.pack("<9f", *expected)
    assert scene.summary.status == scene.summary.placement_status == "complete"
    with pytest.raises(FrozenInstanceError):
        n.count = 0


@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
def test_refinement_normal_lifetime_and_wrapper(wrapper, zip_factory):
    body, attr, _, codes = normal_shell()
    wire = NULL + b"q" + refined(body)
    data = compressed(wire + b"z") if wrapper == "compressed" else raw(wire + b"\0")
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    del doc
    gc.collect()
    m = scene.summary.meshes[0]
    assert (
        m.refinement.attribute_status == "complete"
        and scene.summary.null_shells[0].mesh_id == m.id
    )
    assert scene.source_bytes(m.vertex_normals.source) == attr
    assert scene.mesh_buffers(m.id).normals.data == struct.pack(
        "<9f", *expected_normals(7, 12, codes)
    )
    assert len(scene.summary.instances) == 1


@pytest.mark.parametrize("scheme", [1, 7])
def test_zero_vertices_and_absent_normals(scheme):
    body, attr, _, _ = normal_shell(scheme, count=0)
    scene = ed.read(raw(body + b"\0")).read_scene(mode="strict")
    m = scene.summary.meshes[0]
    assert m.normal_count == m.vertex_normals.count == 0
    assert scene.mesh_buffers(m.id).normals is None
    assert scene.source_bytes(m.vertex_normals.source) == attr
    scene = ed.read(raw(shell() + b"\0")).read_scene(mode="strict")
    assert scene.summary.meshes[0].vertex_normals is None


def test_polar_positive_y_and_xyz_not_normalized():
    body = normal_shell(codes=[0, 0, 4095, 0, 0, 4095])[0]
    scene = ed.read(raw(body + b"\0")).read_scene(mode="strict")
    values = struct.unpack(
        "<9f", scene.mesh_buffers(scene.summary.meshes[0].id).normals.data
    )
    assert values[1] == values[4] == 1 and values[7] == -1
    # f32 pi is not exact pi: the final pole is intentionally not clamped.
    assert values[6] != 0 and values[8] != 0
    body = normal_shell(1, 8, codes=[255] * 9)[0]
    scene = ed.read(raw(body + b"\0")).read_scene(mode="strict")
    assert scene.mesh_buffers(scene.summary.meshes[0].id).normals.data == struct.pack(
        "<9f", *([1.0] * 9)
    )


@pytest.mark.parametrize("kind", ["shell", "mesh"])
def test_raw_normals_are_byte_exact_and_described(kind):
    body = (
        shell(normals=True)
        if kind == "shell"
        else grid()[:1]
        + b"\x08"
        + grid()[2:]
        + b"\x11"
        + struct.pack("<3f", -0.0, 0.0, 2.0) * 6
        + b"\0"
    )
    scene = ed.read(raw(body + b"\0")).read_scene(mode="strict")
    m = scene.summary.meshes[0]
    n = m.vertex_normals
    assert n.encoding == "f32_xyz" and n.packing == "f32_le"
    assert n.compression is n.bits_per_sample is None and n.bounds == ()
    assert scene.mesh_buffers(m.id).normals.data == scene.source_bytes(n.values_source)


@pytest.mark.parametrize("scheme", [0, 2, 3, 6, 8, 255])
def test_unimplemented_normal_schemes_fail_closed(scheme):
    body, attr, _, _ = normal_shell()
    body = body.replace(attr, bytes([1, scheme]) + attr[2:])
    doc = ed.read(raw(body + b"\0"))
    assert doc.parse_hsf().summary.stages.hsf_syntax == "partial"
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.read_scene(mode="strict")


@pytest.mark.parametrize("bits", [0, 1, 32, 255])
def test_invalid_bit_width_rejected(bits):
    body, attr, _, _ = normal_shell()
    body = body.replace(attr, attr[:2] + bytes([bits]) + attr[3:])
    with pytest.raises(ed.UnsupportedFeatureError):
        ed.read(raw(body + b"\0")).read_scene(mode="strict")


@pytest.mark.parametrize("delta", [-4, 4])
def test_wrong_packed_length_rejected(delta):
    body, attr, packed, _ = normal_shell()
    body = body.replace(
        attr, attr[:3] + struct.pack("<i", len(packed) + delta) + packed
    )
    with pytest.raises(ed.InvalidFormatError):
        ed.read(raw(body + b"\0")).read_scene()


def test_normal_allocation_budget():
    data = raw(normal_shell()[0] + b"\0")
    baseline = ed.read(data).read_scene()
    with pytest.raises(ed.LimitExceededError):
        ed.read(
            data,
            limits=ed.Limits(max_output_bytes=baseline.summary.usage.output_bytes - 1),
        ).read_scene()
