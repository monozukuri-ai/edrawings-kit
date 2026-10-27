"""Independent wire fixtures for Polygon and RGB8 Color Map."""

import gc
import json
import struct
import subprocess
import sys
import zlib

import edrawings_kit as ed
import pytest
from test_scene import unpack
from test_user_data_audit import sample
from test_views import PROFILE, compressed, raw

POINTS = ((0, 0, 0), (2, 0, 0), (1, 1, 0), (2, 2, 0), (0, 2, 0))
POLYGON = b"G" + struct.pack("<i15f", 5, *(x for p in POINTS for x in p))
COLORS = bytes([255, 0, 0, 0, 255, 0])
PALETTE = b"\x0c\0" + struct.pack("<i", 2) + COLORS


@pytest.mark.parametrize("version", ["8.05", "14.50", "19.10"])
@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed"])
@pytest.mark.parametrize("deflated", [False, True])
def test_polygon_sources_order_and_reference_survive_owner(
    version, wrapper, deflated, zip_factory
):
    body = b"(\x01a" + POLYGON + b"qr\0\0\0\0)"
    hsf = f";; HSF V{version} \n".encode() + (
        b"Z" + zlib.compress(body + b"z") + b"\0" if deflated else body + b"\0"
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
    (p,) = s.primitives
    assert s.status == s.placement_status == "complete"
    assert p.kind == "polygon" and p.point_count == 5 and p.part_lengths == ()
    assert unpack(scene.primitive_points(p.id)) == POINTS
    assert scene.source_bytes(p.points_source) == POLYGON[5:]
    assert scene.source_bytes(p.source) == POLYGON
    assert p.center is None and p.text is None and not s.meshes
    assert s.references[0].target_id == p.id and len(s.primitive_instances) == 2


@pytest.mark.parametrize("count", [0, 1, 2, 256, 65536])
def test_palette_source_is_preserved_without_expanding_or_applying_colors(count):
    colors = bytes([21, 34, 55]) * count
    record = b"\x0c\0" + struct.pack("<i", count) + colors
    doc = ed.read(raw(b"~\x01\xff\0\0" + record + b"\x08\x01\0" + POLYGON + b"\0"))
    hsf = doc.parse_hsf(mode="strict")
    m = hsf.summary.records[1].color_map
    assert isinstance(m, ed.ColorMapLayout)
    assert (m.format, m.entry_count) == (0, count)
    assert hsf.source_bytes(m.colors) == colors
    scene = doc.read_scene()
    s = scene.summary
    assert s.placement_status == "unsupported" and not s.primitive_instances
    assert [r.kind for r in s.rendering_options] == ["color_map", "color_by_index"]
    assert s.nodes[0].face_color is None
    assert unpack(scene.primitive_points(s.primitives[0].id)) == POINTS
    with pytest.raises(ed.UnsupportedFeatureError) as e:
        doc.read_scene(mode="strict")
    assert e.value.diagnostic.code == "hsf.rendering_semantics"


@pytest.mark.parametrize("record", [POLYGON, PALETTE])
def test_every_operand_cut_is_invalid_in_both_modes(record):
    for cut in range(len(record)):
        for mode in ("strict", "partial"):
            with pytest.raises(ed.InvalidFormatError):
                ed.read(raw(record[:cut])).parse_hsf(mode=mode)


@pytest.mark.parametrize("format", [1, 2, 255])
def test_unknown_palette_format_has_no_resync(format):
    doc = ed.read(raw(bytes([12, format]) + POLYGON + b"\0"))
    h = doc.parse_hsf().summary
    assert not h.records and h.domains[0].parsed_bytes == h.header.byte_len
    assert h.diagnostics[0].code == "hsf.color_map_format"
    assert h.diagnostics[0].opcode == 12
    assert h.unparsed[0].offset == h.header.byte_len
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.parse_hsf(mode="strict")


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_polygon_requires_finite_points(value):
    bad = POLYGON[:5] + struct.pack("<f", value) + POLYGON[9:]
    for mode in ("strict", "partial"):
        with pytest.raises(ed.InvalidFormatError) as e:
            ed.read(raw(bad + b"\0")).parse_hsf(mode=mode)
        assert e.value.diagnostic.code == "hsf.nonfinite_polygon"


def test_counts_and_limits():
    for n in (-1, 0, 1, 2):
        with pytest.raises(ed.InvalidFormatError):
            ed.read(raw(b"G" + struct.pack("<i", n))).parse_hsf()
    with pytest.raises(ed.InvalidFormatError):
        ed.read(raw(b"\x0c\0" + struct.pack("<i", -1))).parse_hsf()
    cases = [
        (POLYGON * 2, ed.Limits(max_hsf_vertices=9), "hsf.limit_vertices"),
        (POLYGON * 2, ed.Limits(max_scene_primitives=1), "hsf.limit_primitives"),
        (PALETTE, ed.Limits(max_hsf_string_bytes=5), "hsf.limit_string"),
        (b"\x0c\0" + struct.pack("<i", 65537), ed.Limits(), "hsf.limit_color_map"),
    ]
    for body, limits, code in cases:
        with pytest.raises(ed.LimitExceededError) as e:
            ed.read(raw(body + b"\0"), limits=limits).read_scene()
        assert e.value.diagnostic.code == code


def test_private_postlude_and_image_stops_are_preserved_and_cli_matches(tmp_path):
    for tail in (b"[\x09\0\0\0\xbe" + bytes(12) + b"]z", b"i" + bytes(40)):
        data = compressed(sample() + b"h\x01" + PALETTE + POLYGON + tail)
        doc = ed.read(data, read_metadata=False)
        assert doc.parse_hsf().summary.domains[1].parsed_bytes == 0
        scene = doc.read_scene(user_data_profile=PROFILE)
        s = scene.summary
        assert len(s.opaque_user_data) == len(s.primitives) == 1
        assert s.placement_status == "unsupported" and not s.primitive_instances
        assert s.hsf.diagnostics[-1].opcode == tail[0]
        remaining = next(
            span for span in s.hsf.unparsed if span.domain_id.endswith("/hsf:1")
        )
        assert scene.source_bytes(remaining).startswith(tail)
        path = tmp_path / "polygon.hsf"
        path.write_bytes(data)
        result = subprocess.run(
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
        assert json.loads(result.stdout) == s.to_dict()
