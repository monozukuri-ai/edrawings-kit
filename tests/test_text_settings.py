import gc
import struct

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_pattern_attributes import read
from test_rendering import F, H
from test_segment_style import named, opened
from test_settings import DEPTH, LOCKS
from test_style_resolution import styled

ANCHORS = (
    "lower_left",
    "upper_left",
    "center_left",
    "lower_right",
    "upper_right",
    "center_right",
    "lower_center",
    "upper_center",
    "center",
    "insertion_point",
)
JUSTIFICATIONS = (None, "left", "center", "right")


@pytest.mark.parametrize("value", range(256))
def test_all_alignment_bytes_preserve_known_and_unknown_components(value):
    doc = read(b"*" + bytes([value]) + grid())
    scene = doc.read_scene()
    d = scene.summary.nodes[0].display
    lo, hi = value & 15, value >> 4
    if lo == 15:
        assert d.text_anchor is None
    else:
        assert d.text_anchor.value.index == lo
        assert d.text_anchor.value.name == (ANCHORS[lo] if lo < 10 else None)
    if hi == 0:
        assert d.text_justification is None
    else:
        assert d.text_justification.value.index == hi
        assert d.text_justification.value.name == (
            JUSTIFICATIONS[hi] if hi < 4 else None
        )
    complete = (lo < 10 or lo == 15) and hi < 4
    assert scene.summary.rendering_options[0].interpretation_status == (
        "complete" if complete else "unsupported"
    )
    assert bool(scene.summary.instances) == complete
    if complete:
        assert doc.read_scene(mode="strict").summary.status == "complete"
    else:
        with pytest.raises(ed.UnsupportedFeatureError):
            doc.read_scene(mode="strict")


def test_no_setting_does_not_erase_prior_component_and_styles_merge_components():
    body = (
        b"*\x25*\x1f*\x03"
        + opened(b"anchor")
        + b"*\x08)"
        + opened(b"just")
        + b"*\x3f)"
        + opened(b"part")
        + styled(b"/anchor")
        + styled(b"/just")
        + grid()
        + b")"
    )
    scene = read(body).read_scene(mode="strict")
    root = scene.summary.nodes[0].display
    assert root.text_anchor.value.name == "lower_right"
    assert root.text_justification.value.name == "left"
    d = scene.summary.instances[0].display
    assert (
        d.text_anchor.value.name == "center"
        and d.text_justification.value.name == "right"
    )
    assert scene.source_bytes(d.text_anchor.source) == b"*\x08"
    assert scene.source_bytes(d.text_justification.source) == b"*\x3f"
    assert scene.summary.style_resolutions[0].status == "complete"


def test_unknown_alignment_cannot_leave_stale_local_attribute():
    scene = read(b"*\x28*\xa5*\x0f" + grid()).read_scene()
    d = scene.summary.nodes[0].display
    assert d.text_anchor.value.name == "center_right"
    assert (
        d.text_justification.value.index == 10
        and d.text_justification.value.name is None
    )
    assert not scene.summary.instances
    assert scene.source_bytes(d.text_justification.source) == b"*\xa5"


def test_style_conflict_and_per_include_parent_alignment():
    conflict = (
        opened(b"a")
        + b"*\x00)"
        + opened(b"b")
        + b"*\x00)"
        + opened(b"p")
        + styled(b"/a")
        + styled(b"/b")
        + grid()
        + b")"
    )
    assert (
        read(conflict).read_scene().summary.style_resolutions[0].reason
        == "hsf.style_conflict"
    )
    body = (
        opened(b"part")
        + grid()
        + b")"
        + opened(b"a")
        + b"*\x11"
        + named(b"<", b"/part")
        + b")"
        + opened(b"b")
        + b"*\x32"
        + named(b"<", b"/part")
        + b")"
    )
    scene = read(body).read_scene(mode="strict")
    assert scene.summary.instances[0].display.text_anchor is None
    assert [i.display.text_anchor.value.name for i in scene.summary.instances[1:]] == [
        "upper_left",
        "center_left",
    ]


def font_flags(mask, value):
    return (
        b"F"
        + bytes([mask & 255, value & 255, (mask >> 8) & 255, (value >> 8) & 255])
        + struct.pack("<HH", mask >> 16, value >> 16)
    )


@pytest.mark.parametrize(
    "bit,name",
    [
        (0x400, "outline"),
        (0x800, "underline"),
        (0x1000, "strikethrough"),
        (0x2000, "overline"),
        (0x4000, "non_proportional"),
        (0x20000, "fill_edges"),
        (0x40000, "bold"),
        (0x80000, "italic"),
    ],
)
@pytest.mark.parametrize("enabled", [False, True])
def test_font_boolean_preferences_preserve_explicit_false(bit, name, enabled):
    wire = font_flags(0x8080 | bit, bit if enabled else 0)
    s = read(wire).read_scene()
    setting = s.summary.rendering_options[0].settings
    assert isinstance(setting, ed.RenderingSettings)
    (flag,) = setting.font_flags
    assert (flag.bit, flag.name, flag.value) == (bit, name, enabled)
    assert s.source_bytes(flag.source) == wire
    assert (
        setting.decoding_status == "complete"
        and setting.interpretation_status == "unsupported"
    )


@pytest.mark.parametrize("units", range(7))
def test_font_size_units_and_scalar_values_are_source_backed(units):
    wire = b"F\x0f\x0f\x03ABC" + struct.pack("<fBfBB", 2.5, units, 50, 5, 1)
    doc = read(wire)
    scene = doc.read_scene()
    del doc
    gc.collect()
    setting = scene.summary.rendering_options[0].settings
    fields = {f.name: f for f in setting.operands}
    assert fields["names"].text.value == "ABC"
    assert fields["size"].floats == (2.5,)
    assert fields["size_units"].integers == (units,)
    assert fields["size_units"].enumeration.name == (
        ("object", "screen", "window", "points", "pixels")[units] if units < 5 else None
    )
    assert fields["tolerance_units"].enumeration.name == "percentage"
    assert fields["transforms"].enumeration.name == "character_glyphs"
    assert scene.source_bytes(fields["size"].source) == struct.pack("<f", 2.5)
    assert setting.decoding_status == ("complete" if units < 5 else "unsupported")
    assert scene.summary.placement_status == "unsupported"


def test_font_off_values_and_unknown_encoding_are_not_defaults():
    s = read(b"F\x07\0").read_scene().summary.rendering_options[0].settings
    assert (s.mask, s.value, s.operands, s.font_flags) == (7, 0, (), ())
    s = read(b"F\x01\x01\x01\xff").read_scene().summary.rendering_options[0].settings
    assert s.operands[0].text.value is None and s.decoding_status == "unsupported"


def test_rendering_and_heuristics_scalars_do_not_enable_effective_rendering():
    scene = read(H + F + DEPTH + LOCKS + grid()).read_scene()
    for event in scene.summary.rendering_options:
        assert event.settings and event.interpretation_status == "unsupported"
        assert event.settings.interpretation_status == "unsupported"
        for operand in event.settings.operands:
            raw = scene.source_bytes(operand.source)
            if operand.encoding == "f32_le":
                assert (
                    struct.pack("<" + "f" * len(operand.floats), *operand.floats) == raw
                )
            elif operand.encoding in ("u8", "u16_le", "u32_le", "i32_le"):
                code = {"u8": "B", "u16_le": "H", "u32_le": "I", "i32_le": "i"}[
                    operand.encoding
                ]
                assert operand.integers == struct.unpack(
                    "<" + code * (len(raw) // struct.calcsize(code)), raw
                )
    assert not scene.summary.instances
    with pytest.raises(ed.LimitExceededError):
        read(
            H + F + DEPTH + LOCKS + grid(),
            limits=ed.Limits(max_output_bytes=scene.summary.usage.output_bytes - 1),
        ).read_scene()
