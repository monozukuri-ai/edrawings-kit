"""Independent bit-string encoder and source-local refinement expectations."""

import gc
import json
import math
import struct
import subprocess
import sys
from dataclasses import FrozenInstanceError, replace

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_rendering import NULL
from test_scene import shell
from test_views import compressed, raw


def packed_codes(codes, width, bits, pad=0):
    if width == 3 and bits == 8:
        return bytes(codes)
    stream = "".join(f"{v:0{bits}b}" for v in codes)
    stream += str(pad) * (-len(stream) % 32)
    return b"".join(
        int(stream[i : i + 32], 2).to_bytes(4, "little")
        for i in range(0, len(stream), 32)
    )


def quantized(kind="shell", width=2, bits=8, version="19.10", bounds=None, pad=0):
    count = 6 if kind == "mesh" else 3
    top = (1 << bits) - 1
    codes = ([0, top, top // 3, top // 2, 1, top - 1] * width)[: count * width]
    bounds = bounds or [(-2.0 - axis, 4.0 + axis) for axis in range(width)]
    packed = packed_codes(codes, width, bits, pad)
    attr = b"\x03\x01" + (bytes([width]) if version != "8.05" else b"")
    attr += struct.pack(
        f"<{2 * width}f", *(b[0] for b in bounds), *(b[1] for b in bounds)
    )
    attr += bytes([bits]) + struct.pack("<i", len(packed)) + packed
    if kind == "mesh":
        base = grid()
        body = base[:1] + b"\x08" + base[2:]
    else:
        base = shell(points=((0, 0, 0), (1, 0, 0), (0, 1, 0)), faces=(3, 0, 1, 2))
        body = base[:1] + b"\x18" + base[2:]
    values = []
    for i, code in enumerate(codes):
        lo, hi = bounds[i % width]
        value = lo if code == 0 else hi if code == top else lo + (hi - lo) * code / top
        values.append(struct.unpack("<f", struct.pack("<f", value))[0])
    return body + attr + b"\0", attr, packed, values


def refinement(body, index=0):
    return body[:1] + bytes([body[1] & ~16]) + struct.pack("<I", index) + body[2:]


@pytest.mark.parametrize("bits", [2, 7, 8, 9, 12, 16, 24, 31])
@pytest.mark.parametrize("width", [1, 2, 3, 4, 5, 128])
def test_shell_bit_boundaries_widths_and_exact_endpoints(bits, width):
    body, attr, packed, values = quantized(width=width, bits=bits)
    scene = ed.read(raw(body + b"\0")).read_scene(mode="strict")
    mesh = scene.summary.meshes[0]
    p = mesh.vertex_parameters
    q = p.quantization
    assert isinstance(q, ed.ParameterQuantization)
    assert (q.bits_per_sample, q.packing) == (
        bits,
        "u8_xyz" if (width, bits) == (3, 8) else "le32_msb",
    )
    assert scene.mesh_buffers(mesh.id).parameters.data == struct.pack(
        f"<{len(values)}f", *values
    )
    assert scene.source_bytes(p.values_source) == packed
    assert scene.source_bytes(p.source) == attr
    assert scene.source_bytes(q.bounds_source) == attr[3 : 3 + width * 8]
    assert q.bounds == tuple((-2 - a, 4 + a) for a in range(width))
    assert scene.summary.status == scene.summary.placement_status == "complete"
    assert not scene.summary.shell_parameter_sets
    with pytest.raises(FrozenInstanceError):
        q.bits_per_sample = 9


@pytest.mark.parametrize("kind", ["mesh", "shell"])
@pytest.mark.parametrize(
    "version,width",
    [
        ("8.05", 3),
        ("14.50", 1),
        ("19.10", 2),
        ("19.10", 3),
        ("19.10", 5),
        ("19.10", 128),
    ],
)
def test_legacy_layouts_and_mesh(kind, version, width):
    body, _, packed, values = quantized(kind, width, version=version)
    scene = ed.read(f";; HSF V{version} \n".encode() + body + b"\0").read_scene(
        mode="strict"
    )
    m = scene.summary.meshes[0]
    assert scene.mesh_buffers(m.id).parameters.data == struct.pack(
        f"<{len(values)}f", *values
    )
    assert scene.source_bytes(m.vertex_parameters.values_source) == packed


@pytest.mark.parametrize("bounds", [[(0, 0), (-3, -3)], [(-3.0e38, 3.0e38), (-2, 4)]])
def test_degenerate_and_large_finite_bounds(bounds):
    # Round bounds to their actual wire f32 representation before expectations.
    bounds = [struct.unpack("<2f", struct.pack("<2f", *b)) for b in bounds]
    body, _, _, expected = quantized(bounds=bounds, bits=31)
    scene = ed.read(raw(body + b"\0")).read_scene(mode="strict")
    values = struct.unpack(
        "<6f", scene.mesh_buffers(scene.summary.meshes[0].id).parameters.data
    )
    assert values == tuple(expected) and all(math.isfinite(v) for v in values)


def test_padding_is_not_data_and_original_bytes_are_retained():
    data = [quantized(width=1, bits=7, pad=p) for p in (0, 1)]
    scenes = [ed.read(raw(d[0] + b"\0")).read_scene(mode="strict") for d in data]
    assert data[0][2] != data[1][2]
    assert [s.mesh_buffers(s.summary.meshes[0].id).parameters.data for s in scenes] == [
        struct.pack("<3f", *data[0][3])
    ] * 2
    for scene, d in zip(scenes, data, strict=True):
        assert (
            scene.source_bytes(scene.summary.meshes[0].vertex_parameters.values_source)
            == d[2]
        )


@pytest.mark.parametrize("kind", ["mesh", "shell"])
@pytest.mark.parametrize("width", [0, 129, 255])
def test_width_outside_bounded_profile_stops_at_original_record(kind, width):
    body, attr, _, _ = quantized(kind, width=5)
    base = body[: -len(attr) - 1]
    bad = base + attr[:2] + bytes([width]) + attr[3:] + b"\0"
    doc = ed.read(raw(bad + b"\0"))
    parsed = doc.parse_hsf()
    assert parsed.summary.diagnostics[-1].code == f"hsf.{kind}_parameter_width"
    assert parsed.summary.unparsed[0].offset == len(raw(b""))
    with pytest.raises(ed.UnsupportedFeatureError, match=f"hsf.{kind}_parameter_width"):
        doc.parse_hsf(mode="strict")


@pytest.mark.parametrize("kind", ["mesh", "shell"])
def test_wide_parameter_truncations_and_shared_budget(kind):
    body, attr, _, _ = quantized(kind, width=5)
    # Every operand truncation must fail; subsequent bytes are never scanned
    # for a new opcode or mistaken for a completed optional-attribute stream.
    for cut in range(len(body) - len(attr), len(body)):
        with pytest.raises(ed.InvalidFormatError):
            ed.read(raw(body[:cut])).parse_hsf(mode="strict")
    data = raw(quantized(kind, width=128)[0] + b"\0")
    scene = ed.read(data).read_scene(mode="strict")
    limit = scene.summary.usage.output_bytes
    limits = replace(ed.Limits(), max_output_bytes=limit)
    assert (
        ed.read(data, limits=limits).read_scene(mode="strict").summary == scene.summary
    )
    with pytest.raises(ed.LimitExceededError):
        ed.read(data, limits=replace(limits, max_output_bytes=limit - 1)).read_scene()


@pytest.mark.parametrize(
    "prefix,reason",
    [
        (NULL + b"q", None),
        (shell() + b"q", None),
        (b"X" + bytes(12) + b"q", "hsf.parameter_target_kind"),
        (b"", "hsf.parameter_target_unresolved"),
    ],
)
@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed", "compressed"])
def test_refinement_targets_sources_lifetime_and_no_placement(
    prefix, reason, wrapper, zip_factory
):
    body, _, packed, values = quantized()
    refined = refinement(body)
    wire = prefix + refined
    data = compressed(wire + b"z") if wrapper == "compressed" else raw(wire + b"\0")
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    s = doc.read_scene()
    applied = prefix == NULL + b"q"
    if applied:
        assert doc.read_scene(mode="strict").summary.status == "complete"
    else:
        with pytest.raises(ed.UnsupportedFeatureError):
            doc.read_scene(mode="strict")
    del doc
    gc.collect()
    item = s.summary.shell_parameter_sets[0]
    assert isinstance(item, ed.ShellParameterSet)
    assert item.association_reason == reason
    assert item.association_status == ("complete" if reason is None else "unsupported")
    targets = (*s.summary.null_shells, *s.summary.meshes)
    assert item.target_id == (targets[0].id if reason is None else None)
    assert s.source_bytes(item.source) == refined
    record = next(r for r in s.summary.hsf.records if r.id == item.source_record_id)
    assert item.vertices_source == record.shell.vertices
    assert s.source_bytes(item.vertex_parameters.values_source) == packed
    b = s.shell_parameters(item.id)
    assert b.dtype == "<f4" and b.shape == (3, 2)
    assert b.data == struct.pack("<6f", *values)
    assert item.interpretation_status == ("complete" if applied else "unsupported")
    assert not s.summary.primitive_instances
    if applied:
        assert len(s.summary.instances) == 1
        assert item.mesh_id == s.summary.meshes[0].id
        assert s.summary.placement_status == s.summary.status == "complete"
    else:
        assert not s.summary.instances and item.mesh_id is None
        assert (
            s.summary.placement_status == "unsupported"
            and s.summary.status == "partial"
        )
    with pytest.raises(ed.InvalidFormatError) as error:
        s.shell_parameters("missing")
    assert error.value.diagnostic.code == "scene.unknown_parameter_set"


def test_association_is_ordered_and_nonzero_lod_has_no_target():
    body = quantized()[0]
    scene = ed.read(
        raw(refinement(body) + NULL + b"q" + refinement(body) + b"\0")
    ).read_scene()
    a, b = scene.summary.shell_parameter_sets
    assert a.target_id is None and b.target_id == scene.summary.null_shells[0].id
    lod = body[:2] + b"\x02" + body[3:]
    s = ed.read(raw(NULL + b"q" + lod + b"\0")).read_scene().summary
    assert s.shell_parameter_sets[0].association_reason == "hsf.parameter_nonzero_lod"
    assert s.shell_parameter_sets[0].lod == 2


def test_invalid_bounds_lengths_truncation_and_resource_limits():
    good = quantized()[0]
    for bounds in [
        [(2, -2), (0, 1)],
        [(0, float("inf")), (0, 1)],
        [(float("nan"), 1), (0, 1)],
    ]:
        # Build wire independently of the expected numeric buffer.
        _, attr, _, _ = quantized()
        bad_attr = (
            attr[:3]
            + struct.pack("<4f", bounds[0][0], bounds[1][0], bounds[0][1], bounds[1][1])
            + attr[19:]
        )
        bad = good[: -len(attr) - 1] + bad_attr + b"\0"
        with pytest.raises(ed.InvalidFormatError):
            ed.read(raw(bad + b"\0")).read_scene()
    with pytest.raises(ed.InvalidFormatError):
        ed.read(raw(good[:-2])).read_scene()
    _, attr, _, _ = quantized()
    bad_attr = attr[:20] + struct.pack("<i", 4) + attr[24:]
    with pytest.raises(ed.InvalidFormatError):
        ed.read(raw(good[: -len(attr) - 1] + bad_attr + b"\0\0")).read_scene()
    for limits in [ed.Limits(max_output_bytes=1000), ed.Limits(max_scene_meshes=1)]:
        with pytest.raises(ed.LimitExceededError):
            ed.read(
                raw(NULL + b"q" + refinement(good) + b"\0"), limits=limits
            ).read_scene()
    with pytest.raises(ed.LimitExceededError):
        ed.read(raw(good + b"\0"), limits=ed.Limits(max_hsf_vertices=2)).read_scene()


def test_cli_and_drawing_keep_refinement_inventory_partial(tmp_path):
    data = raw(NULL + b"q" + refinement(quantized()[0]) + b"\0")
    doc = ed.read(data)
    summary = doc.read_scene().summary
    drawing = doc.read_drawing().summary
    assert drawing.scene.shell_parameter_sets == summary.shell_parameter_sets
    assert drawing.assessment.status == "partial"
    path = tmp_path / "parameters.hsf"
    path.write_bytes(data)
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path)],
        capture_output=True,
        encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout)["shell_parameter_sets"] == [
        s.to_dict() for s in summary.shell_parameter_sets
    ]
