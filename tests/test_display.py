"""Independent wire fixtures for display attributes and retained definitions."""

import io
import json
import struct
import subprocess
import sys
import zipfile

import edrawings_kit as ed
import pytest
from test_user_data_audit import sample
from test_views import POINTS, PROFILE, compressed, raw


def visibility(mask, value):
    out = b"V" + bytes([mask & 255, value & 255])
    if mask & 128:
        out += struct.pack("<HH", mask >> 8 & 65535, value >> 8 & 65535)
    if mask & 0x800000:
        out += bytes([mask >> 24, value >> 24])
    return out


def size(value, units=None):
    return b"+" + struct.pack("<f", value) + (b"" if units is None else bytes([units]))


def style(name=b"dash", definition=b"(1, -1)"):
    return (
        b"J"
        + bytes([len(name)])
        + name
        + struct.pack("<H", len(definition))
        + definition
    )


def font(data=b"", name=b"enfield", encoding=5, lookup=b""):
    return (
        b"f\0"
        + bytes([len(name)])
        + name
        + bytes([encoding, len(lookup)])
        + lookup
        + struct.pack("<i", len(data))
        + data
    )


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed", "compressed"])
def test_public_models_source_ranges_and_definition_continuation(wrapper):
    v = visibility(0x03FFFFFF, 0x01000201)
    b = (
        v
        + size(-4, 4)
        + style()
        + style(definition=b"\xffz\0")
        + font(bytes(range(256)))
        + b"l"
        + POINTS
    )
    data = compressed(b + b"z") if wrapper == "compressed" else raw(b + b"\0")
    if wrapper in ("zip", "prefixed"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("eModel", data)
        data = stream.getvalue()
        if wrapper == "prefixed":
            from conftest import PREFIX

            data = PREFIX + data
    doc = ed.read(data)
    h = doc.parse_hsf(mode="strict")
    records = {r.kind: r for r in h.summary.records}
    assert isinstance(records["visibility"].visibility, ed.VisibilityLayout)
    assert records["visibility"].visibility.mask == 0x03FFFFFF
    assert records["visibility"].visibility.value == 0x01000201
    assert h.source_bytes(records["visibility"].source) == v
    assert isinstance(records["marker_size"].marker_size, ed.MarkerSizeLayout)
    assert records["marker_size"].marker_size.units == 4
    assert records["font"].font.data.length == 256
    s = doc.read_scene()
    assert len(s.summary.line_styles) == 2 and len(s.summary.fonts) == 1
    line_style = s.summary.line_styles[1]
    assert (
        isinstance(line_style, ed.LineStyleDefinition)
        and line_style.definition.value is None
    )
    assert s.source_bytes(line_style.definition.source) == b"\xffz\0"
    f = s.summary.fonts[0]
    assert isinstance(f, ed.FontDefinition) and f.name.value == "enfield"
    assert f.name.encoding == "ascii" and f.encoding == 5
    assert s.source_bytes(f.data_source) == bytes(range(256))
    assert f.interpretation_status == line_style.interpretation_status == "unsupported"
    assert not s.summary.primitive_instances
    assert s.summary.placement_status == "unsupported"
    i = s.summary.nodes[0]
    assert len(i.display.visibility) == 32 and len(i.display.colors) == 32
    for bit in (7, 23, 26, 31):
        assert i.display.visibility[bit] is None
    assert i.display.visibility[9].value is True
    assert i.display.visibility[24].value is True
    assert i.display.visibility[25].value is False
    assert isinstance(i.display.marker_size.value, ed.MarkerSize)
    assert i.display.marker_size.value.value == 4
    assert i.display.marker_size.value.units == "pixels"
    assert s.source_bytes(i.display.marker_size.source) == size(-4, 4)
    assert s.primitive_points(s.summary.primitives[0].id).data == POINTS
    assert s.summary.processed_records == len(h.summary.records)
    with pytest.raises(ed.UnsupportedFeatureError) as e:
        doc.read_scene(mode="strict")
    assert e.value.diagnostic.code == "hsf.line_style_definition"


@pytest.mark.parametrize(
    "units,name",
    [
        (None, "relative"),
        (0, "object"),
        (1, "screen"),
        (2, "window"),
        (3, "points"),
        (4, "pixels"),
    ],
)
def test_marker_size_units(units, name):
    s = ed.read(raw(size(0.5 if units is None else -0.5, units) + b"\0")).read_scene(
        mode="strict"
    )
    assert s.summary.nodes[0].display.marker_size.value.units == name
    assert s.summary.nodes[0].display.marker_size.value.value == 0.5
    assert s.summary.units is None


def test_mesh_receives_extended_attributes_without_rewriting_buffers():
    from test_scene import shell

    s = ed.read(
        raw(visibility(0x00000281, 0x200) + size(-2, 0) + shell() + b"\0")
    ).read_scene(mode="strict")
    i = s.summary.instances[0]
    assert i.face_visible.value is False
    assert i.display.visibility[9].value is True
    assert i.display.marker_size.value.units == "object"


def test_definition_limits_and_malformed_data_are_fatal():
    for body in (style(), font()):
        doc = ed.read(raw(body + b"\0"), limits=ed.Limits(max_scene_definitions=0))
        with pytest.raises(ed.LimitExceededError) as e:
            doc.read_scene()
        assert e.value.diagnostic.code == "hsf.limit_definitions"
    for body in (style(definition=b"x" * 300), font(b"x" * 300)):
        doc = ed.read(raw(body + b"\0"), limits=ed.Limits(max_hsf_string_bytes=299))
        with pytest.raises(ed.LimitExceededError):
            doc.parse_hsf()
    for value in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ed.InvalidFormatError):
            ed.read(raw(size(value, 4) + b"\0")).parse_hsf()
    with pytest.raises(ed.InvalidFormatError):
        ed.read(raw(font()[:-4] + b"\xff" * 4)).parse_hsf()
    for body in (visibility(0x03FFFFFF, 0), size(-2, 4), style(), font(b"]h\0")):
        for cut in range(len(body)):
            with pytest.raises(ed.InvalidFormatError):
                ed.read(raw(body[:cut])).parse_hsf()


@pytest.mark.parametrize(
    "body,code",
    [
        (size(-1, 5), "hsf.marker_size_units"),
        (b"f\x01", "hsf.font_format"),
        (visibility(0x08800080, 0), "hsf.visibility_mask"),
        (b"~\x80\x80\x80\x80", "hsf.color_mask"),
    ],
)
def test_unknown_operands_stop_at_original_opcode(body, code):
    doc = ed.read(raw(b"h\0" + body + b"h\x01\0"))
    h = doc.parse_hsf()
    assert len(h.summary.records) == 1
    assert h.summary.diagnostics[0].code == code
    assert h.source_bytes(h.summary.unparsed[0]).startswith(body)
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.parse_hsf(mode="strict")


def test_user_data_still_withholds_world_placements():
    body = b"h\0" + visibility(0xFFFF, 1) + style() + font() + size(0.5) + b"l" + POINTS
    doc = ed.read(compressed(sample() + body + b"z"))
    s = doc.read_scene(user_data_profile=PROFILE)
    assert s.summary.processed_records == len(s.summary.hsf.records)
    assert s.summary.line_styles and s.summary.fonts and s.summary.primitives
    assert s.summary.placement_status == "unsupported"
    assert not s.summary.instances and not s.summary.primitive_instances
    assert doc.read_scene().summary.processed_records == 3


def test_cli_exposes_definitions_and_units(tmp_path):
    path = tmp_path / "display.hsf"
    path.write_bytes(raw(style() + font() + size(-2, 4) + b"\0"))
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path)],
        capture_output=True,
        encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    data = json.loads(run.stdout)
    assert data["fonts"][0]["name"]["value"] == "enfield"
    assert data["nodes"][0]["display"]["marker_size"]["value"]["units"] == "pixels"
