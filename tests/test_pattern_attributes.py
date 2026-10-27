"""Public numeric wire values and independent attribute-inheritance scenarios."""

import gc
import json
import struct
import subprocess
import sys
from dataclasses import FrozenInstanceError

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_segment_style import named, opened
from test_style_resolution import styled
from test_views import compressed, raw

PATTERNS = (
    "solid",
    "dash_dot",
    "dashed",
    "dotted",
    "dash_dot_dot",
    "dash_dot_dot_dot",
    "long_dash",
    "center_line",
    "phantom_line",
    "fine_dotted",
)
CAPS = ("none", "round", "square")
JOINS = ("miter", "round", "bevel")


def pattern(op=b"-", index=2, cap=1, join=2):
    return op + bytes([index, cap | (join << 4)])


def read(body, version="19.10", **kwargs):
    return ed.read(f";; HSF V{version} \n".encode() + body + b"\0", **kwargs)


@pytest.mark.parametrize(
    "opcode,field", [(b"-", "line_pattern"), (b"\r", "edge_pattern")]
)
@pytest.mark.parametrize("index", range(10))
@pytest.mark.parametrize("cap,join", [(c, j) for c in range(3) for j in range(3)])
def test_every_numeric_pattern_cap_and_join(opcode, field, index, cap, join):
    wire = pattern(opcode, index, cap, join)
    scene = read(wire + grid()).read_scene(mode="strict")
    attr = getattr(scene.summary.nodes[0].display, field)
    assert isinstance(attr, ed.LinePatternAttribute) and isinstance(
        attr.value, ed.LinePattern
    )
    assert attr.value.index == index | (cap << 8) | (join << 12)
    assert (attr.value.pattern, attr.value.cap, attr.value.join) == (
        PATTERNS[index],
        CAPS[cap],
        JOINS[join],
    )
    assert attr.value.name is None and attr.value.interpretation_status == "complete"
    assert scene.source_bytes(attr.source) == wire
    assert getattr(scene.summary.instances[0].display, field) == attr
    assert scene.summary.status == scene.summary.placement_status == "complete"
    assert scene.summary.rendering_options[0].interpretation_status == "complete"
    with pytest.raises(FrozenInstanceError):
        attr.value.index = 0


@pytest.mark.parametrize("index", range(49))
def test_every_public_marker_index(index):
    scene = read(b"@" + bytes([index]) + b"X" + struct.pack("<3f", 1, 2, 3)).read_scene(
        mode="strict"
    )
    attr = scene.summary.nodes[0].display.marker_symbol
    assert isinstance(attr, ed.MarkerSymbolAttribute) and isinstance(
        attr.value, ed.MarkerSymbol
    )
    assert attr.value.index == index and attr.value.name is None
    assert attr.value.symbol and attr.value.interpretation_status == "complete"
    assert scene.summary.primitive_instances[0].display.marker_symbol == attr
    assert scene.source_bytes(attr.source) == b"@" + bytes([index])
    if index in (0, 6, 9, 38, 44, 45, 46, 47, 48):
        assert (
            attr.value.symbol
            == {
                0: "circle",
                6: "dot",
                9: "star",
                38: "hash",
                44: "vertical_bar",
                45: "slash",
                46: "backslash",
                47: "y",
                48: "z",
            }[index]
        )


@pytest.mark.parametrize("version", ["8.05", "14.50", "19.10"])
def test_numeric_versions_and_no_implicit_defaults(version):
    scene = read(
        pattern() + pattern(b"\r", 9, 2, 1) + b"@\x09" + grid(), version
    ).read_scene(mode="strict")
    d = scene.summary.instances[0].display
    assert (
        d.line_pattern.value.pattern,
        d.edge_pattern.value.pattern,
        d.marker_symbol.value.symbol,
    ) == ("dashed", "fine_dotted", "star")
    d = read(grid(), version).read_scene(mode="strict").summary.instances[0].display
    assert d.line_pattern is d.edge_pattern is d.marker_symbol is None


def inheritance_body():
    return (
        pattern(index=1)
        + b"@\x00"
        + opened(b"library")
        + pattern(b"\r", 3)
        + opened(b"base")
        + pattern(index=2)
        + b"@\x06q))"
        + opened(b"style")
        + styled(b"/library/base")
        + b")"
        + opened(b"part")
        + styled(b"/style")
        + pattern(b"\r", 4)
        + grid()
        + b")"
        + b"s\0\0\0\0"
        + pattern(index=7, cap=2, join=0)
        + b"@\x09)"
    )


@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
def test_style_final_reopen_precedence_and_source_lifetime(wrapper, zip_factory):
    body = inheritance_body()
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    del doc
    gc.collect()
    d = scene.summary.instances[0].display
    assert (
        d.line_pattern.value.pattern == "center_line"
        and d.line_pattern.value.cap == "square"
    )
    assert (
        d.edge_pattern.value.pattern == "dash_dot_dot"
        and d.marker_symbol.value.symbol == "star"
    )
    assert scene.source_bytes(d.line_pattern.source) == pattern(index=7, cap=2, join=0)
    assert scene.source_bytes(d.marker_symbol.source) == b"@\x09"
    for resolution in scene.summary.style_resolutions:
        assert resolution.status == "complete"
        assert resolution.display.line_pattern.value.pattern == "center_line"
    base = next(n for n in scene.summary.nodes if n.name == "base")
    assert base.display.edge_pattern is None  # library parent cannot leak through Style
    part = next(n for n in scene.summary.nodes if n.name == "part")
    assert part.display.line_pattern is None and part.display.marker_symbol is None


def test_include_parent_is_per_instance_and_local_overrides_style():
    body = (
        opened(b"part")
        + grid()
        + b")"
        + opened(b"a")
        + pattern(index=1)
        + b"@\x06"
        + named(b"<", b"/part")
        + b")"
        + opened(b"b")
        + pattern(index=3)
        + b"@\x09"
        + named(b"<", b"/part")
        + b")"
    )
    scene = read(body).read_scene(mode="strict")
    a, b, c = scene.summary.instances
    assert a.display.line_pattern is None
    assert [x.display.line_pattern.value.pattern for x in (b, c)] == [
        "dash_dot",
        "dotted",
    ]
    assert [x.display.marker_symbol.value.symbol for x in (b, c)] == ["dot", "star"]
    body = (
        opened(b"style")
        + pattern(index=2)
        + b"@\x06)"
        + opened(b"part")
        + styled(b"/style")
        + pattern(index=0, cap=0, join=0)
        + b"@\x09"
        + grid()
        + b")"
    )
    d = read(body).read_scene(mode="strict").summary.instances[0].display
    assert (
        d.line_pattern.value.pattern,
        d.line_pattern.value.cap,
        d.line_pattern.value.join,
        d.marker_symbol.value.symbol,
    ) == ("solid", "none", "miter", "star")


@pytest.mark.parametrize("wire", [pattern(), pattern(b"\r"), b"@\x06"])
def test_duplicate_styles_conflict_even_with_equal_values(wire):
    body = (
        opened(b"a")
        + wire
        + b")"
        + opened(b"b")
        + wire
        + b")"
        + opened(b"p")
        + styled(b"/a")
        + styled(b"/b")
        + grid()
        + b")"
    )
    doc = read(body)
    s = doc.read_scene().summary
    assert s.style_resolutions[0].reason == "hsf.style_conflict" and not s.instances
    with pytest.raises(ed.UnsupportedFeatureError) as error:
        doc.read_scene(mode="strict")
    assert error.value.diagnostic.code == "hsf.style_conflict"


def test_disjoint_styles_merge_line_edge_and_marker():
    body = (
        opened(b"a")
        + pattern()
        + b")"
        + opened(b"b")
        + pattern(b"\r")
        + b"@\x06)"
        + opened(b"p")
        + styled(b"/a")
        + styled(b"/b")
        + grid()
        + b")"
    )
    s = read(body).read_scene(mode="strict").summary
    assert s.style_resolutions[0].status == "complete"
    assert (
        s.instances[0].display.line_pattern
        and s.instances[0].display.edge_pattern
        and s.instances[0].display.marker_symbol
    )


@pytest.mark.parametrize(
    "opcode,field",
    [(b"-", "line_pattern"), (b"\r", "edge_pattern"), (b"@", "marker_symbol")],
)
@pytest.mark.parametrize("name", [b"edw-dashed", b"solid", b"", b"a\0b", b"\xff"])
def test_named_assignments_remain_opaque_and_replace_local_state(opcode, field, name):
    known = b"@\x09" if opcode == b"@" else pattern(opcode)
    wire = opcode + b"\xff" + bytes([len(name)]) + name
    doc = read(known + wire + grid())
    scene = doc.read_scene()
    attr = getattr(scene.summary.nodes[0].display, field)
    assert attr.value.index is None and attr.value.name.value == (
        name.decode("ascii") if name.isascii() else None
    )
    assert (
        scene.source_bytes(attr.value.name.source) == name
        and scene.source_bytes(attr.source) == wire
    )
    assert attr.value.interpretation_status == "unsupported"
    assert (attr.value.symbol if opcode == b"@" else attr.value.pattern) is None
    assert (
        not scene.summary.instances and scene.summary.placement_status == "unsupported"
    )
    with pytest.raises(ed.UnsupportedFeatureError) as error:
        doc.read_scene(mode="strict")
    assert error.value.diagnostic.code == "hsf.rendering_semantics"


@pytest.mark.parametrize(
    "wire,field",
    [
        (pattern(index=10), "line_pattern"),
        (pattern(cap=3), "line_pattern"),
        (pattern(join=3), "line_pattern"),
        (pattern(b"\r", index=254, cap=15, join=15), "edge_pattern"),
        (b"@\x31", "marker_symbol"),
        (b"@\xfe", "marker_symbol"),
    ],
)
def test_unknown_numeric_fields_do_not_fall_back(wire, field):
    doc = read(pattern() + pattern(b"\r") + b"@\x09" + wire + grid())
    scene = doc.read_scene()
    attr = getattr(scene.summary.nodes[0].display, field)
    assert (
        attr.value.interpretation_status == "unsupported"
        and scene.source_bytes(attr.source) == wire
    )
    assert not scene.summary.instances
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.read_scene(mode="strict")


def test_unknown_style_and_later_known_assignment_do_not_erase_uncertainty():
    s = (
        read(
            opened(b"lib")
            + b"@\xff\x04star)"
            + opened(b"p")
            + styled(b"/lib")
            + grid()
            + b")"
        )
        .read_scene()
        .summary
    )
    assert s.style_resolutions[0].reason == "hsf.style_target_attributes"
    scene = read(b"@\xfe@\x09" + grid()).read_scene()
    assert scene.summary.nodes[0].display.marker_symbol.value.symbol == "star"
    assert not scene.summary.instances and scene.summary.status == "partial"


def test_original_tag_is_not_reassigned_and_limits_apply():
    data = raw(grid() + b"q" + pattern() + b"@\x09r\0\0\0\0\0")
    scene = ed.read(data).read_scene(mode="strict")
    assert len(scene.summary.instances) == 2
    assert len(scene.summary.meshes) == 1
    assert all(
        i.display.marker_symbol.value.symbol == "star" for i in scene.summary.instances
    )
    with pytest.raises(ed.LimitExceededError):
        ed.read(
            data,
            limits=ed.Limits(max_output_bytes=scene.summary.usage.output_bytes - 1),
        ).read_scene(mode="strict")
    with pytest.raises(ed.LimitExceededError):
        read(b"@\xff\x04star", limits=ed.Limits(max_hsf_string_bytes=3)).read_scene()


def test_cli_and_drawing_expose_typed_attributes(tmp_path):
    path = tmp_path / "patterns.hsf"
    path.write_bytes(raw(inheritance_body() + b"\0"))
    doc = ed.read_file(path)
    scene = doc.read_scene(mode="strict")
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path), "--mode", "strict"],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(run.stdout)["instances"] == [
        i.to_dict() for i in scene.summary.instances
    ]
    assert doc.read_drawing().summary.scene.instances == scene.summary.instances
    assert doc.read_drawing().summary.assessment.status == "partial"
