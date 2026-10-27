"""Shared axis and text-region fixtures, authored independently of the parser."""

import gc
import itertools
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


def batch(modes=(0, 3, 1), explicit=False):
    lengths = (2, 3)
    points = []
    for part, length in enumerate(lengths):
        for _ in range(length):
            points.append(
                tuple(
                    len(points) * 10 + axis + 0.125
                    if mode == 0
                    else 0.0
                    if mode == 1
                    else 100.5 + axis
                    if mode == 2
                    else part * 100 + axis + 10.5
                    for axis, mode in enumerate(modes)
                )
            )
    flags = sum(mode << (8 + axis * 2) for axis, mode in enumerate(modes)) | (
        2 if explicit else 0
    )
    wire = b"\x10" + struct.pack("<Hi", flags, 5)
    if explicit:
        wire += struct.pack("<i", 2)
    wire += struct.pack("<2i", *lengths)
    main = [p[a] for p in points for a in range(3) if modes[a] == 0]
    tail = []
    for axis, mode in enumerate(modes):
        if mode == 2:
            tail.append(points[0][axis])
        elif mode == 3:
            tail += [points[0][axis], points[2][axis]]
    main_bytes = struct.pack(f"<{len(main)}f", *main)
    tail_bytes = struct.pack(f"<{len(tail)}f", *tail)
    return wire + main_bytes + tail_bytes, tuple(points), main_bytes, tail_bytes


def region(options=0, count=2, encoded=True):
    prefix = b"x" if encoded else b"T"
    prefix += struct.pack("<3f", 4, 5, 6)
    prefix += b"\x05\x02A\0" if encoded else b"\x01A"
    coords = struct.pack(f"<{count * 3}f", *range(count * 3))
    return prefix + bytes([1, options, count]) + coords, coords


@pytest.mark.parametrize("explicit", [False, True])
@pytest.mark.parametrize(
    "modes", [m for m in itertools.product(range(4), repeat=3) if 0 in m]
)
def test_shared_axes_round_trip_order_counts_and_reference(modes, explicit):
    record, expected, main, tail = batch(modes, explicit)
    for version in ("8.05", "14.50", "19.10"):
        data = f";; HSF V{version} \n".encode() + record + b"qr\0\0\0\0\0"
        scene = ed.read(data).read_scene(mode="strict")
        s = scene.summary
        (p,) = s.primitives
        layout = s.hsf.records[0].poly_polyline
        assert s.status == s.placement_status == "complete"
        assert p.part_lengths == (2, 3) and p.point_count == 5
        assert unpack(scene.primitive_points(p.id)) == expected
        assert layout.dimensions == modes.count(0)
        assert p.points_source == layout.points
        assert scene.source_bytes(layout.points) == main
        assert scene.source_bytes(layout.leftovers) == tail
        assert layout.leftovers.offset == layout.points.offset + layout.points.length
        assert s.references[0].target_id == p.id and len(s.primitive_instances) == 2


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed"])
@pytest.mark.parametrize("deflated", [False, True])
def test_source_ownership_domains_and_opaque_region(wrapper, deflated, zip_factory):
    b, expected, main, tail = batch((2, 0, 3))
    text, coords = region(31, 4)
    body = b"(\x01a" + text + b + b")"
    data = raw(b"Z" + zlib.compress(body + b"z") + b"\0" if deflated else body + b"\0")
    if wrapper != "raw":
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene()
    with pytest.raises(ed.UnsupportedFeatureError) as e:
        doc.read_scene(mode="strict")
    assert e.value.diagnostic.code == "hsf.text_region_semantics"
    del doc
    gc.collect()
    s = scene.summary
    text_p, poly = s.primitives
    assert text_p.text.value == "A"
    assert unpack(scene.primitive_points(text_p.id)) == ((4, 5, 6),)
    records = {r.id: r for r in s.hsf.records}
    text_layout = records[text_p.source_record_id].primitive
    tr = text_layout.text_region
    assert isinstance(tr, ed.TextRegionLayout)
    assert (tr.options, tr.point_count) == (31, 4)
    assert scene.source_bytes(tr.points) == coords
    assert tr.points.domain_id == text_p.source.domain_id
    assert unpack(scene.primitive_points(poly.id)) == expected
    layout = records[poly.source_record_id].poly_polyline
    assert (
        scene.source_bytes(layout.points) == main
        and scene.source_bytes(layout.leftovers) == tail
    )
    assert layout.leftovers.domain_id == poly.source.domain_id
    assert s.rendering_options[0].source_record_id == text_p.source_record_id
    assert s.placement_status == "unsupported" and not s.primitive_instances


@pytest.mark.parametrize("encoded", [False, True])
@pytest.mark.parametrize("count", [0, 1, 2, 3, 4])
def test_text_region_counts_keep_text_anchor_separate(encoded, count):
    record, coords = region(count=count, encoded=encoded)
    hsf = ed.read(raw(record + b"\0")).parse_hsf(mode="strict")
    layout = hsf.summary.records[0].primitive
    assert layout.point_count == 1 and layout.text_region.point_count == count
    assert hsf.source_bytes(layout.text_region.points) == coords
    assert hsf.source_bytes(layout.points) == struct.pack("<3f", 4, 5, 6)


@pytest.mark.parametrize(
    "record",
    [
        batch((2, 0, 3))[0],
        batch((3, 3, 0), True)[0],
        region()[0],
        region(31, 4, False)[0],
    ],
)
def test_every_truncation_is_invalid(record):
    for end in range(len(record)):
        for mode in ("strict", "partial"):
            with pytest.raises(ed.InvalidFormatError):
                ed.read(raw(record[:end])).parse_hsf(mode=mode)


def test_unknown_region_and_batch_profiles_stop_without_resync():
    prefix = region()[0][:-27]
    cases = [
        (prefix + b"\x02", "hsf.text_options"),
        (prefix + b"\x81", "hsf.text_options"),
        (prefix + b"\x01\x20", "hsf.text_region_options"),
        (prefix + b"\x01\0\x05", "hsf.text_region_count"),
    ]
    cases += [
        (b"\x10" + struct.pack("<H", flags), "hsf.poly_polyline_flags")
        for flags in (1, 4, 6, 8, 0x4000, 0x8000)
    ]
    for body, code in cases:
        doc = ed.read(raw(body + b"h\x01\0"))
        s = doc.parse_hsf().summary
        assert not s.records and s.domains[0].parsed_bytes == s.header.byte_len
        assert s.diagnostics[0].code == code
        with pytest.raises(ed.UnsupportedFeatureError):
            doc.parse_hsf(mode="strict")


def test_finite_leftovers_regions_and_shared_resource_caps():
    b = batch((0, 3, 1))[0]
    text = region()[0]
    for record in (b, text):
        for value in (float("nan"), float("inf"), float("-inf")):
            bad = record[:-4] + struct.pack("<f", value)
            with pytest.raises(ed.InvalidFormatError):
                ed.read(raw(bad + b"\0")).parse_hsf()
    for body, limits, code in [
        (text, ed.Limits(max_hsf_vertices=2), "hsf.limit_vertices"),
        (b + text, ed.Limits(max_hsf_vertices=7), "hsf.limit_vertices"),
        (b, ed.Limits(max_scene_primitives=1), "hsf.limit_primitives"),
        (b, ed.Limits(max_hsf_records=1), "hsf.limit_poly_polyline_parts"),
        (b, ed.Limits(max_output_bytes=128), "budget.output"),
    ]:
        with pytest.raises(ed.LimitExceededError) as e:
            ed.read(raw(body + b"\0"), limits=limits).read_scene()
        assert e.value.diagnostic.code == code


def test_experimental_header_cli_and_following_stop_remain_explicit(tmp_path):
    text, _ = region()
    tail = b"[\x09\0\0\0\xbe" + bytes(16) + b"]z"
    data = compressed(sample() + b"h\x01" + batch()[0] + text + tail)
    doc = ed.read(data, read_metadata=False)
    assert doc.parse_hsf().summary.domains[1].parsed_bytes == 0
    s = doc.read_scene(user_data_profile=PROFILE).summary
    assert len(s.primitives) == 2 and not s.primitive_instances
    assert s.hsf.diagnostics[-1].code == "hsf.unsupported_user_data"
    path = tmp_path / "text-axis.hsf"
    path.write_bytes(data)
    output = subprocess.run(
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
    assert json.loads(output.stdout) == s.to_dict()
