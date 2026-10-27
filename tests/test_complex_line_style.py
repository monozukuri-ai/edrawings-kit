"""Parallel programs: retained operands, explicit units and unresolved defaults."""

import gc
import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_line_style import definition, use
from test_pattern_attributes import read
from test_segment_style import opened
from test_style_resolution import styled
from test_views import compressed, raw

OBSERVED = (
    b"0.006350 oru dash,0.001270 oru blank,0.001270 oru dash,0.001270 oru blank, "
    b"parallel, 1.5 weight, 0.01000 oru dash, blank, 0.01000 oru dash, segmented"
)


def explicit_program(unit=b"pixels", fixed=False, offset=b"-2"):
    modifier = b" fixed" if fixed else b""
    return (
        b"1 oru dash, 2 px blank, parallel, "
        + offset
        + b" "
        + unit
        + modifier
        + b" offset, 1.5 "
        + unit
        + modifier
        + b" weight, dash, 3 px blank, segmented"
    )


@pytest.mark.parametrize("name", [b"custom", b"edw-thin/thick chain", b"edw-$6"])
def test_real_program_is_structured_without_guessing_omitted_weight_units(name):
    doc = read(definition(name, OBSERVED) + use(name) + grid())
    scene = doc.read_scene()
    d = scene.summary.line_styles[0]
    program = d.program
    assert isinstance(program, ed.LineStyleProgram)
    assert program.kind == "parallel_dash_blank" and not program.elements
    assert program.interpretation_status == "unsupported"
    assert program.reason == "hsf.line_style_weight_units"
    a, b = program.parallels
    assert isinstance(a, ed.LineStyleParallel) and isinstance(
        b.weight, ed.LineStyleMeasure
    )
    assert a.weight is a.offset is a.marker_source is a.segmented_source is None
    assert len(a.elements) == 4 and len(b.elements) == 3
    assert scene.source_bytes(a.source) == OBSERVED.split(b", parallel")[0]
    assert scene.source_bytes(b.source) == OBSERVED.split(b", ", 1)[1]
    assert scene.source_bytes(b.marker_source) == b"parallel"
    assert b.weight.value == 1.5 and b.weight.units is None
    assert b.weight.units_source is b.weight.fixed_source is None and not b.weight.fixed
    assert scene.source_bytes(b.weight.source) == b"1.5 weight"
    assert scene.source_bytes(b.weight.value_source) == b"1.5"
    blank = b.elements[1]
    assert blank.stretchable and blank.length is blank.units is None
    assert blank.length_source is blank.units_source is None
    assert scene.source_bytes(blank.source) == b"blank"
    assert scene.source_bytes(b.segmented_source) == b"segmented"
    assert not scene.summary.instances and len(scene.summary.meshes) == 1
    assert d.reason == ("hsf.line_style_name" if name == b"edw-$6" else program.reason)
    with pytest.raises(ed.UnsupportedFeatureError) as error:
        doc.read_scene(mode="strict")
    assert error.value.diagnostic.code == "hsf.line_style_definition"


@pytest.mark.parametrize(
    "unit,expected",
    [
        (b"oru", "object_relative"),
        (b"px", "pixels"),
        (b"pixel", "pixels"),
        (b"pixels", "pixels"),
    ],
)
@pytest.mark.parametrize("fixed", [False, True])
@pytest.mark.parametrize("offset", [b"-2", b"0", b"+2.5e-3"])
def test_explicit_parallel_weights_offsets_and_reset_are_complete(
    unit, expected, fixed, offset
):
    program = explicit_program(unit, fixed, offset)
    scene = read(
        definition(program=program) + use() + use(opcode=b"\r") + grid()
    ).read_scene(mode="strict")
    parsed = scene.summary.line_styles[0].program
    assert parsed.interpretation_status == "complete" and parsed.reason is None
    a, b = parsed.parallels
    assert not a.elements[0].stretchable and a.elements[0].length == 1
    assert b.elements[0].stretchable and b.elements[0].length is None
    assert (b.weight.value, b.weight.units, b.weight.fixed) == (1.5, expected, fixed)
    assert (b.offset.value, b.offset.units, b.offset.fixed) == (
        float(offset),
        expected,
        fixed,
    )
    assert scene.source_bytes(b.offset.value_source) == offset
    for m in (b.weight, b.offset):
        assert scene.source_bytes(m.units_source) == unit
        assert (scene.source_bytes(m.fixed_source) if m.fixed_source else None) == (
            b"fixed" if fixed else None
        )
    assert (
        scene.summary.placement_status == "complete"
        and len(scene.summary.instances) == 1
    )
    assert all(
        e.line_style_binding.status == "complete"
        for e in scene.summary.rendering_options
    )
    with pytest.raises(FrozenInstanceError):
        b.weight.value = 2


@pytest.mark.parametrize(
    "program",
    [
        b"blank",
        b"dash, blank",
        b"1 oru dash, blank",
        b"1 oru dash, segmented",
        b"segmented, 1 oru dash",
        b"dash, parallel, blank",
        b"2 px weight, dash",
        b"-2 oru offset, blank",
        b"dash, parallel, dash, parallel, dash",
    ],
)
def test_supported_partial_and_unsized_programs(program):
    p = (
        read(definition(program=program) + use() + grid())
        .read_scene(mode="strict")
        .summary
    )
    assert p.line_styles[0].program.kind == "parallel_dash_blank"
    assert p.line_styles[0].program.parallels and p.placement_status == "complete"


@pytest.mark.parametrize(
    "program",
    [
        b"parallel, dash",
        b"dash, parallel",
        b"dash, parallel, parallel, dash",
        b"segmented",
        b"segmented, segmented, dash",
        b"dash, segmented, segmented",
        b"1 px weight, 2 px weight, dash",
        b"1 px offset, 2 px offset, dash",
        b"dash, 2 px weight",
        b"dash, 2 px offset",
        b"1 px weight, 2 px offset, dash",
        b"1 offset, dash",
        b"1 fixed weight, dash",
        b"1 world weight, dash",
        b"0 px weight, dash",
        b"-1 px weight, dash",
        b"nan px weight, dash",
        b"inf px offset, dash",
        b"1e999 px offset, dash",
        b"dash, parallel, fit, dash",
        b"dash, parallel, glyph",
        b"1 px fixed fixed weight, dash",
        b"1.5 weight, dash, unknown",
    ],
)
def test_unknown_or_ambiguous_modifier_sequences_keep_whole_program_unsupported(
    program,
):
    doc = read(definition(program=program) + use() + grid())
    scene = doc.read_scene()
    assert scene.summary.line_styles[0].program is None
    assert scene.summary.line_styles[0].reason == "hsf.line_style_program"
    assert not scene.summary.instances
    assert scene.source_bytes(scene.summary.line_styles[0].definition.source) == program
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.read_scene(mode="strict")


@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
@pytest.mark.parametrize("version", ["14.50", "19.10"])
def test_bound_complex_program_style_inheritance_source_lifetime(
    version, wrapper, zip_factory
):
    body = (
        opened(b"style")
        + use()
        + b")"
        + opened(b"part")
        + styled(b"/style")
        + grid()
        + b")"
        + definition(program=explicit_program())
    )
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    data = data.replace(b"V19.10", b"V" + version.encode(), 1)
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    del doc
    gc.collect()
    d = scene.summary.line_styles[0]
    assert scene.summary.style_resolutions[0].status == "complete"
    assert (
        scene.summary.instances[0].display.line_pattern.value.binding.definition_id
        == d.id
    )
    assert (
        scene.source_bytes(d.program.parallels[1].weight.source) == b"1.5 pixels weight"
    )
    assert scene.summary.nodes[2].display.line_pattern is None


def test_limits_before_program_output_and_no_geometry_change():
    program = b", parallel, ".join([b"dash"] * 32)
    s = read(definition(program=program) + use() + grid()).read_scene(mode="strict")
    assert len(s.summary.line_styles[0].program.parallels) == 32
    baseline = read(grid()).read_scene(mode="strict")
    assert s.mesh_buffers(s.summary.meshes[0].id) == baseline.mesh_buffers(
        baseline.summary.meshes[0].id
    )
    with pytest.raises(ed.LimitExceededError) as error:
        read(definition(program=program + b", parallel, dash")).read_scene()
    assert error.value.diagnostic.code == "hsf.limit_line_style_parallels"
    with pytest.raises(ed.LimitExceededError):
        read(
            definition(program=program) + use() + grid(),
            limits=ed.Limits(max_output_bytes=s.summary.usage.output_bytes - 1),
        ).read_scene()
    with pytest.raises(ed.LimitExceededError):
        read(definition(program=b",".join([b"dash"] * 257))).read_scene()


def test_cli_and_drawing_expose_unresolved_weight_without_enabling_placements(tmp_path):
    path = tmp_path / "complex.hsf"
    path.write_bytes(raw(definition(program=OBSERVED) + use() + grid() + b"\0"))
    doc = ed.read_file(path)
    scene = doc.read_scene()
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path)],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(run.stdout)["line_styles"] == [
        d.to_dict() for d in scene.summary.line_styles
    ]
    assert doc.read_drawing().summary.scene.line_styles == scene.summary.line_styles
