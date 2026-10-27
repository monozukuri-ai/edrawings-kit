"""Independent bounded revision-47 bitmap envelope fixtures, not vendor bytes."""

import struct
from dataclasses import replace

import edrawings_kit as ed
import pytest
from test_terminal_user_data import FIRST, PROFILE, first, packed


def bitmap_tail(count=1, width=3, height=-2):
    stride = (width * 3 + 3) // 4 * 4
    pixels = b"]z[\0" * (stride * abs(height) // 4)
    carrier = bytearray(96)
    struct.pack_into(
        "<IiiHHIIiiII",
        carrier,
        32,
        40,
        width,
        height,
        1,
        24,
        0,
        len(pixels),
        0,
        0,
        0,
        0,
    )
    record = struct.pack("<I", 96) + carrier + struct.pack("<I", len(pixels)) + pixels
    return (
        b"["
        + struct.pack("<IBIII", 9, 190, 47, 0, count)
        + record * count
        + bytes(4)
        + b"]z"
    )


def data(tail, *, revision=47, middle=b"h\0\1", parent=b"\0"):
    return packed(first(revision) + middle + tail, parent=parent)


@pytest.mark.parametrize("count,width,height", [(1, 3, -2), (14, 3, 2), (11, 120, -90)])
def test_terminal_bitmaps_complete_boundary_and_retained_source(count, width, height):
    tail = bitmap_tail(count, width, height)
    doc = ed.read(data(tail))
    parsed = doc.parse_hsf(user_data_profile=PROFILE)
    assert not parsed.summary.unparsed
    record = parsed.summary.records[-3]
    u = record.user_data
    assert u.profile.endswith("revision-47-bitmaps-v1")
    assert u.declared_length == 9 and u.computed_payload_length == len(tail) - 7
    assert len(u.fields) == 8 + count * 4
    assert parsed.source_bytes(record.source) == tail[:-1]
    at = record.source.offset
    for field in u.fields:
        assert field.source.offset == at
        at += field.source.length
    assert at == parsed.summary.records[-2].source.offset
    assert (
        parsed.summary.stages.hsf_syntax == "partial" and not u.native_reader_verified
    )
    scene = doc.read_scene(user_data_profile=PROFILE).summary
    assert scene.processed_records == len(parsed.summary.records)
    assert len(scene.opaque_user_data) == 2
    assert scene.placement_status == "unsupported" and not scene.instances
    assert doc.parse_hsf(user_data_profile=FIRST).summary.unparsed
    with pytest.raises(ed.UnsupportedFeatureError, match="hsf.experimental_user_data"):
        doc.parse_hsf(user_data_profile=PROFILE, mode="strict")


def test_every_truncation_and_boundary_mismatch_stops_at_original_terminal():
    tail = bitmap_tail()
    invalid = [tail[:cut] for cut in range(1, len(tail))]
    # Prefix, reserved, count, carrier length, DIB format and pixel length.
    for offset in [
        1,
        5,
        6,
        10,
        14,
        18,
        54,
        58,
        62,
        66,
        68,
        70,
        74,
        86,
        118,
        len(tail) - 6,
    ]:
        bad = bytearray(tail)
        bad[offset] ^= 0x80
        invalid.append(bytes(bad))
    invalid += [tail + b"z", tail + b"\0", tail[:-2] + b"\0]z"]
    for value in invalid:
        parsed = ed.read(data(value)).parse_hsf(user_data_profile=PROFILE)
        assert parsed.summary.domains[1].parsed_bytes == len(first(47)) + 3
        assert len([r for r in parsed.summary.records if r.user_data]) == 1


@pytest.mark.parametrize("count", [0, 15, 2**32 - 1])
def test_bitmap_count_is_bounded_before_carrier_iteration(count):
    tail = bytearray(bitmap_tail())
    struct.pack_into("<I", tail, 14, count)
    parsed = ed.read(data(tail)).parse_hsf(user_data_profile=PROFILE)
    assert parsed.summary.diagnostics[-1].code == "edrawings.user_data_profile_mismatch"
    assert parsed.summary.domains[1].parsed_bytes == len(first(47)) + 3


@pytest.mark.parametrize(
    "kwargs", [{"revision": 46}, {"middle": b"h\0"}, {"parent": b"h\0\0"}]
)
def test_bitmap_tail_requires_exact_revision_and_terminal_context(kwargs):
    parsed = ed.read(data(bitmap_tail(), **kwargs)).parse_hsf(user_data_profile=PROFILE)
    assert len([r for r in parsed.summary.records if r.user_data]) == 1


@pytest.mark.parametrize("height,accepted", [(85, True), (86, False)])
def test_terminal_borrowed_window_has_a_hard_one_mib_cap(height, accepted):
    tail = bitmap_tail(width=4096, height=height)
    assert (len(tail) <= 1 << 20) == accepted
    # Deliberately repetitive synthetic pixels; separate compression-ratio
    # policy from the framing-window bound being tested here.
    limits = replace(ed.Limits(), max_compression_ratio=100_000)
    parsed = ed.read(data(tail), limits=limits).parse_hsf(user_data_profile=PROFILE)
    assert bool(parsed.summary.unparsed) != accepted
    if not accepted:
        assert parsed.summary.domains[1].parsed_bytes == len(first(47)) + 3


def test_maximum_metadata_count_uses_shared_output_budget():
    value = data(bitmap_tail(count=14))
    parsed = ed.read(value).parse_hsf(user_data_profile=PROFILE)
    limit = parsed.summary.usage.output_bytes
    limits = replace(ed.Limits(), max_output_bytes=limit)
    assert (
        not ed.read(value, limits=limits)
        .parse_hsf(user_data_profile=PROFILE)
        .summary.unparsed
    )
    with pytest.raises(ed.LimitExceededError, match="budget.output"):
        ed.read(value, limits=replace(limits, max_output_bytes=limit - 1)).parse_hsf(
            user_data_profile=PROFILE
        )
