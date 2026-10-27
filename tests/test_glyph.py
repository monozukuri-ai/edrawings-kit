import json
import struct
import subprocess
import sys

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_line_style import use
from test_pattern_attributes import read
from test_segment_style import opened
from test_style_resolution import styled
from test_views import compressed, raw

CROSS = bytes([10, 0, 0, 2, 246, 0, 10, 0, 2, 0, 246, 0, 10, 0])


def glyph(name=b"crosshairs", data=CROSS):
    return b"j" + bytes([len(name)]) + name + struct.pack("<H", len(data)) + data


@pytest.mark.parametrize("version", ["14.50", "19.10"])
@pytest.mark.parametrize("forward", [False, True])
@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
def test_glyph_framing_program_and_root_marker_binding(
    version, forward, wrapper, zip_factory
):
    usage = use(b"crosshairs", b"@") + b"X" + struct.pack("<3f", 1, 2, 3)
    body = usage + glyph() if forward else glyph() + usage
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    data = data.replace(b"V19.10", b"V" + version.encode(), 1)
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    h = doc.parse_hsf(mode="strict")
    record = next(r for r in h.summary.records if r.glyph)
    assert isinstance(record.glyph, ed.GlyphLayout)
    assert h.source_bytes(record.glyph.definition) == CROSS
    scene = doc.read_scene(mode="strict")
    (d,) = scene.summary.glyphs
    assert isinstance(d, ed.GlyphDefinition) and isinstance(d.program, ed.GlyphProgram)
    assert d.program.nominal_radius == 10 and d.program.offset == (0, 0)
    assert [c.kind for c in d.program.commands] == ["polyline", "polyline"]
    assert d.program.commands[0].points == ((-10, 0), (10, 0))
    assert scene.source_bytes(d.program.commands[0].source) == CROSS[3:8]
    assert scene.source_bytes(d.program.termination_source) == b"\0"
    symbol = scene.summary.primitive_instances[0].display.marker_symbol.value
    assert symbol.symbol == "custom" and symbol.binding.definition_id == d.id
    assert (
        symbol.binding.status == "complete"
        and symbol.binding == scene.summary.rendering_options[0].glyph_binding
    )
    assert scene.summary.status == "complete"


@pytest.mark.parametrize(
    "code,points,colors",
    [
        (-1, 0, 0),
        (-2, 0, 0),
        (-3, 0, 0),
        (-4, 2, 0),
        (-5, 3, 0),
        (-6, 2, 0),
        (-7, 2, 0),
        (-8, 0, 0),
        (-9, 0, 0),
        (-10, 0, 3),
        (-11, 0, 1),
    ],
)
def test_drawing_commands_are_retained_without_applying_fill_color_or_curves(
    code, points, colors
):
    payload = bytes(range(points * 2 + colors))
    scene = read(
        glyph(data=bytes([10, 1, 255, code & 255]) + payload + b"\0") + grid()
    ).read_scene()
    (d,) = scene.summary.glyphs
    assert d.program.offset == (1, -1) and d.reason == "hsf.glyph_drawing_state"
    (c,) = d.program.commands
    assert c.code == code and len(c.points) == points and len(c.color) == colors
    assert scene.source_bytes(c.payload_source) == payload
    assert not scene.summary.instances
    with pytest.raises(ed.UnsupportedFeatureError):
        read(glyph(data=bytes([10, 0, 0, code & 255]) + payload + b"\0")).read_scene(
            mode="strict"
        )


@pytest.mark.parametrize(
    "data,reason",
    [
        (b"\0\0\0\0", "header"),
        (b"\x80\0\0\0", "header"),
        (b"\x0a\x80\0\0", "header"),
        (b"\x0a\0\0\xf4\0", "instruction"),
        (b"\x0a\0\0\x01\x80\0\0", "coordinate"),
    ],
)
def test_unknown_glyph_profiles_keep_exact_bytes(data, reason):
    scene = read(glyph(data=data)).read_scene()
    d = scene.summary.glyphs[0]
    assert d.program is None and d.reason == "hsf.glyph_" + reason
    assert scene.source_bytes(d.definition_source) == data


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"\x0a\0\0",
        b"\x0a\0\0\x01",
        b"\x0a\0\0\x01\0",
        b"\x0a\0\0\0x",
        b"\x0a\0\0\x02\0\0\0",
    ],
)
def test_malformed_known_programs_are_fatal(data):
    for mode in ("partial", "strict"):
        with pytest.raises(ed.InvalidFormatError):
            read(glyph(data=data)).read_scene(mode=mode)


@pytest.mark.parametrize(
    "prefix,name,reason",
    [
        (b"", b"missing", "missing"),
        (glyph(), b"CROSSHAIRS", "name_case"),
        (glyph() + glyph(), b"crosshairs", "ambiguous"),
        (glyph() + glyph(b"CROSSHAIRS"), b"crosshairs", "ambiguous"),
        (opened(b"lib") + glyph() + b")", b"crosshairs", "scope"),
        (glyph(b"star"), b"star", "name"),
    ],
)
def test_glyph_resolution_refuses_ambiguous_or_nonroot_definitions(
    prefix, name, reason
):
    scene = read(prefix + use(name, b"@") + grid()).read_scene()
    assert (
        scene.summary.rendering_options[0].glyph_binding.reason == "hsf.glyph_" + reason
    )
    assert not scene.summary.instances


def test_marker_style_binding_final_overwrite_and_incomplete_scene():
    scene = read(
        glyph()
        + opened(b"style")
        + use(b"crosshairs", b"@")
        + b")"
        + opened(b"part")
        + styled(b"/style")
        + grid()
        + b")"
    ).read_scene(mode="strict")
    assert (
        scene.summary.instances[0].display.marker_symbol.value.binding.definition_id
        == scene.summary.glyphs[0].id
    )
    s = (
        read(glyph() + use(b"crosshairs", b"@") + b"@\x09" + grid())
        .read_scene(mode="strict")
        .summary
    )
    assert (
        s.nodes[0].display.marker_symbol.value.symbol == "star"
        and s.nodes[0].display.marker_symbol.value.binding is None
    )
    s = read(glyph() + use(b"crosshairs", b"@") + b"\xfe").read_scene().summary
    assert s.rendering_options[0].glyph_binding.reason == "hsf.glyph_incomplete_scene"


def test_glyph_resource_limits_version_gate_and_all_wire_cuts():
    for limits in (
        ed.Limits(max_scene_definitions=0),
        ed.Limits(max_hsf_string_bytes=4),
    ):
        with pytest.raises(ed.LimitExceededError):
            read(glyph(), limits=limits).read_scene()
    for data, code in [
        (b"\x0a\0\0" + b"\xf8" * 513 + b"\0", "commands"),
        (b"\x0a\0\0" + (b"\x7f" + b"\0\0" * 127) * 33 + b"\0", "points"),
    ]:
        with pytest.raises(ed.LimitExceededError) as error:
            read(glyph(data=data)).read_scene()
        assert error.value.diagnostic.code == "hsf.limit_glyph_" + code
    wire = glyph()
    for cut in range(len(wire)):
        with pytest.raises(ed.InvalidFormatError):
            ed.read(raw(wire[:cut])).parse_hsf()
    h = read(wire, version="8.05").parse_hsf().summary
    assert h.diagnostics[0].code == "hsf.glyph_version"
    s = read(wire + use(b"crosshairs", b"@")).read_scene().summary
    with pytest.raises(ed.LimitExceededError):
        read(
            wire + use(b"crosshairs", b"@"),
            limits=ed.Limits(max_output_bytes=s.usage.output_bytes - 1),
        ).read_scene()


def test_glyph_cli_drawing_and_source_lifetime(tmp_path):
    p = tmp_path / "glyph.hsf"
    p.write_bytes(raw(glyph() + use(b"crosshairs", b"@") + b"*\x21" + grid() + b"\0"))
    doc = ed.read_file(p)
    scene = doc.read_scene(mode="strict")
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(p), "--mode", "strict"],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(run.stdout)["glyphs"] == [
        g.to_dict() for g in scene.summary.glyphs
    ]
    assert doc.read_drawing().summary.scene.glyphs == scene.summary.glyphs
    del doc
    assert scene.source_bytes(scene.summary.glyphs[0].definition_source) == CROSS
