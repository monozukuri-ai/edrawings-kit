"""Custom definition programs, exact file-root bindings and conservative failures."""

import gc
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_display import style
from test_pattern_attributes import pattern, read
from test_segment_style import named, opened
from test_style_resolution import styled
from test_views import compressed, raw


def use(name=b"custom", opcode=b"-"):
    return opcode + b"\xff" + bytes([len(name)]) + name


def definition(name=b"custom", program=b"2 px dash,0.000635 oru blank"):
    return style(name, program)


@pytest.mark.parametrize(
    "unit,expected",
    [
        (b"oru", "object_relative"),
        (b"px", "pixels"),
        (b"pixel", "pixels"),
        (b"pixels", "pixels"),
    ],
)
@pytest.mark.parametrize("number", [b"1", b"0.006350", b"+2.5e-3", b".25", b"1."])
def test_explicit_lengths_keep_units_and_exact_operand_sources(unit, expected, number):
    program = b" \t" + number + b" " + unit + b" dash ,\n3 oru blank\r"
    scene = read(definition(program=program) + use() + grid()).read_scene(mode="strict")
    d = scene.summary.line_styles[0]
    assert (
        isinstance(d.program, ed.LineStyleProgram)
        and d.program.kind == "explicit_dash_blank"
    )
    a, b = d.program.elements
    assert isinstance(a, ed.LineStyleElement)
    assert (a.kind, a.length, a.units) == ("dash", float(number), expected)
    assert (b.kind, b.length, b.units) == ("blank", 3, "object_relative")
    assert scene.source_bytes(a.source) == number + b" " + unit + b" dash"
    assert scene.source_bytes(a.length_source) == number
    assert scene.source_bytes(a.units_source) == unit
    assert scene.source_bytes(b.source) == b"3 oru blank"
    assert scene.source_bytes(d.definition.source) == program
    assert d.reason is None and d.interpretation_status == "complete"
    assert scene.summary.placement_status == "complete"
    assert len(scene.summary.instances) == 1
    with pytest.raises(FrozenInstanceError):
        a.length = 0


@pytest.mark.parametrize("program", [b"", b" \t\r\n", b"dash", b" dash\t"])
def test_solid_definition_has_no_fabricated_lengths(program):
    scene = read(definition(program=program) + use()).read_scene(mode="strict")
    p = scene.summary.line_styles[0].program
    assert p.kind == "solid" and not p.elements
    attr = scene.summary.nodes[0].display.line_pattern.value
    assert attr.pattern == "custom" and attr.cap is attr.join is None


@pytest.mark.parametrize(
    "program",
    [
        b"parallel, 1 px dash",
        b"fit",
        b"offset 1 px",
        b"1 world dash",
        b"1 points dash",
        b"1 PX dash",
        b"1 px Dash",
        b"solid",
        b"0 px dash",
        b"-1 px blank",
        b"NaN px dash",
        b"inf px dash",
        b"1e999 px dash",
        b"1e-999 px dash",
        b"1_000 px dash",
        b"? px dash",
        b"1 px dash,",
        b",1 px dash",
        b"1 px dash extra",
        b"1 px dash\0",
        b"1 px dash\xff",
        b"1 px dash\x0b",
        b"1 px dash\x0c",
    ],
)
def test_unknown_program_never_returns_a_supported_prefix_or_placements(program):
    doc = read(definition(program=program) + use() + grid())
    scene = doc.read_scene()
    d = scene.summary.line_styles[0]
    assert d.program is None and d.reason == "hsf.line_style_program"
    assert scene.source_bytes(d.definition.source) == program
    binding = scene.summary.rendering_options[0].line_style_binding
    assert binding.definition_id == d.id and binding.reason == "hsf.line_style_program"
    assert not scene.summary.instances and len(scene.summary.meshes) == 1
    with pytest.raises(ed.UnsupportedFeatureError) as error:
        doc.read_scene(mode="strict")
    assert error.value.diagnostic.code == "hsf.line_style_definition"


@pytest.mark.parametrize("version", ["14.50", "19.10"])
@pytest.mark.parametrize("forward", [False, True])
@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
def test_unique_file_root_name_before_or_after_use(
    version, forward, wrapper, zip_factory
):
    usage = opened(b"part") + use() + use(opcode=b"\r") + grid() + b")"
    body = usage + definition() if forward else definition() + usage
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    data = data.replace(b"V19.10", b"V" + version.encode(), 1)
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    del doc
    gc.collect()
    d = scene.summary.line_styles[0]
    assert d.context_node_id == scene.summary.nodes[0].id and d.id.startswith(
        "entry:0/" if wrapper in ("zip", "prefixed") else "raw:0/"
    )
    for attr in (
        scene.summary.instances[0].display.line_pattern,
        scene.summary.instances[0].display.edge_pattern,
    ):
        value = attr.value
        assert (
            value.pattern == "custom" and value.cap is value.join is value.index is None
        )
        assert isinstance(value.binding, ed.LineStyleBinding)
        assert (
            value.binding.definition_id == d.id and value.binding.status == "complete"
        )
        assert (
            value.binding.scope == "file_root_unique" and value.binding.reason is None
        )
        assert scene.source_bytes(value.name.source) == b"custom"
        assert scene.source_bytes(attr.source) in (use(), use(opcode=b"\r"))
    assert all(
        e.interpretation_status == "complete" for e in scene.summary.rendering_options
    )
    assert all(
        e.line_style_binding.definition_id == d.id
        for e in scene.summary.rendering_options
    )


@pytest.mark.parametrize(
    "defs,name,reason",
    [
        (b"", b"edw-gestrichelt", "missing"),
        (definition(), b"CUSTOM", "name_case"),
        (definition() + definition(), b"custom", "ambiguous"),
        (definition() + definition(b"CUSTOM"), b"custom", "ambiguous"),
        (opened(b"child") + definition() + b")", b"custom", "scope"),
        (definition(), b"custom, cap=round", "name"),
        (definition(), b"custom\0", "name"),
        (definition(), b"\xff", "name"),
        (definition(), b"", "name"),
    ],
)
def test_ambiguous_missing_scoped_or_nonliteral_names_are_not_guessed(
    defs, name, reason
):
    doc = read(defs + use(name) + grid())
    s = doc.read_scene().summary
    binding = s.rendering_options[0].line_style_binding
    assert (
        binding.status == "unsupported" and binding.reason == "hsf.line_style_" + reason
    )
    assert s.nodes[0].display.line_pattern.value.binding == binding
    assert not s.instances
    with pytest.raises(ed.UnsupportedFeatureError) as error:
        doc.read_scene(mode="strict")
    assert error.value.diagnostic.code == "hsf.rendering_semantics"
    assert error.value.diagnostic.impact == binding.reason


@pytest.mark.parametrize(
    "name", [b"0", b"9", b"solid", b"DASHED", b"dash", b"star?", b"custom "]
)
def test_reserved_or_decorated_definition_names_do_not_shadow_builtins(name):
    s = read(definition(name) + pattern() + grid()).read_scene().summary
    assert s.line_styles[0].program and s.line_styles[0].reason == "hsf.line_style_name"
    assert s.nodes[0].display.line_pattern.value.pattern == "dashed"
    assert not s.instances and s.placement_status == "unsupported"


def inheritance_body():
    return (
        definition()
        + opened(b"library")
        + use()
        + b")"
        + opened(b"part")
        + styled(b"/library")
        + use(opcode=b"\r")
        + grid()
        + b")"
        + opened(b"other")
        + styled(b"/library")
        + pattern(index=0)
        + grid()
        + b")"
    )


def test_bound_pattern_inherits_via_style_local_overrides_and_include_parent():
    s = read(inheritance_body()).read_scene(mode="strict").summary
    assert s.style_resolutions[0].status == "complete"
    assert (
        s.instances[0].display.line_pattern.value.binding.definition_id
        == s.line_styles[0].id
    )
    assert s.instances[0].display.edge_pattern.value.pattern == "custom"
    assert s.instances[1].display.line_pattern.value.pattern == "solid"
    assert s.instances[1].display.line_pattern.value.binding is None
    body = (
        definition()
        + opened(b"part")
        + grid()
        + b")"
        + opened(b"placed")
        + use()
        + named(b"<", b"/part")
        + b")"
    )
    s = read(body).read_scene(mode="strict").summary
    assert s.instances[0].display.line_pattern is None
    assert (
        s.instances[1].display.line_pattern.value.binding.definition_id
        == s.line_styles[0].id
    )


def test_style_cannot_import_nonroot_definitions():
    body = (
        opened(b"library")
        + definition()
        + use()
        + b")"
        + opened(b"part")
        + styled(b"/library")
        + grid()
        + b")"
    )
    s = read(body).read_scene().summary
    assert s.rendering_options[0].line_style_binding.reason == "hsf.line_style_scope"
    assert (
        s.style_resolutions[0].reason == "hsf.style_target_attributes"
        and not s.instances
    )


@pytest.mark.parametrize("stop", [b"\xfe", opened(b"../outside") + b")"])
def test_incomplete_scene_never_resolves_even_an_earlier_definition(stop):
    s = read(definition() + use() + grid() + stop).read_scene().summary
    assert (
        s.rendering_options[0].line_style_binding.reason
        == "hsf.line_style_incomplete_scene"
    )
    assert not s.instances


def test_history_preserved_without_replacing_a_later_local_value():
    s = (
        read(use() + pattern() + definition() + grid())
        .read_scene(mode="strict")
        .summary
    )
    assert s.rendering_options[0].line_style_binding.status == "complete"
    assert s.nodes[0].display.line_pattern.value.pattern == "dashed"
    assert s.nodes[0].display.line_pattern.value.binding is None
    s = read(use(b"missing") + pattern() + definition() + grid()).read_scene().summary
    assert s.nodes[0].display.line_pattern.value.pattern == "dashed" and not s.instances
    assert s.rendering_options[0].line_style_binding.reason == "hsf.line_style_missing"


def test_named_marker_is_not_bound_to_line_style():
    s = read(definition() + use(opcode=b"@") + grid()).read_scene().summary
    assert s.nodes[0].display.marker_symbol.value.interpretation_status == "unsupported"
    assert s.rendering_options[0].line_style_binding is None and not s.instances


def test_definition_program_limits_and_unsupported_unused_program():
    doc = read(definition(program=b",".join([b"1 px dash"] * 256)) + use() + grid())
    s = doc.read_scene(mode="strict").summary
    assert len(s.line_styles[0].program.elements) == 256
    with pytest.raises(ed.LimitExceededError):
        read(
            definition(program=b",".join([b"1 px dash"] * 256)) + use() + grid(),
            limits=ed.Limits(max_output_bytes=s.usage.output_bytes - 1),
        ).read_scene(mode="strict")
    with pytest.raises(ed.LimitExceededError) as error:
        read(definition(program=b",".join([b"1 px dash"] * 257))).read_scene()
    assert error.value.diagnostic.code == "hsf.limit_line_style_elements"
    with pytest.raises(ed.LimitExceededError):
        read(
            definition() + use() + grid(), limits=ed.Limits(max_output_bytes=1000)
        ).read_scene()
    with pytest.raises(ed.LimitExceededError):
        read(definition(), limits=ed.Limits(max_hsf_string_bytes=6)).read_scene()
    s = read(definition(program=b"parallel") + grid()).read_scene().summary
    assert s.meshes and not s.instances
    s = read(definition(), version="8.05").parse_hsf().summary
    assert s.diagnostics[0].code == "hsf.line_style_version"


def test_cli_and_drawing_share_programs_and_bindings(tmp_path):
    path = tmp_path / "custom.hsf"
    path.write_bytes(raw(inheritance_body() + b"\0"))
    doc = ed.read_file(path)
    scene = doc.read_scene(mode="strict")
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path), "--mode", "strict"],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(run.stdout)["line_styles"] == [
        d.to_dict() for d in scene.summary.line_styles
    ]
    assert doc.read_drawing().summary.scene.line_styles == scene.summary.line_styles
    assert doc.read_drawing().summary.scene.instances == scene.summary.instances
