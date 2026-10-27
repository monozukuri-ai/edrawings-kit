"""Source-backed extended line definitions, with unresolved orientation explicit."""

import json
import subprocess
import sys
from dataclasses import FrozenInstanceError

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_line_style import definition, use
from test_pattern_attributes import read
from test_segment_style import named, opened
from test_style_resolution import styled
from test_views import compressed, raw


@pytest.mark.parametrize("unit", [b"px", b"pixel", b"pixels", b"oru", None])
@pytest.mark.parametrize(
    "placement", [b"contrast", b"dash, contrast", b"contrast, parallel, contrast"]
)
def test_contrast_is_a_distinct_color_role_with_exact_lengths(unit, placement):
    prefix = b"2.5 " + unit + b" " if unit else b""
    program = placement.replace(b"contrast", prefix + b"contrast")
    scene = read(
        definition(program=program) + use() + use(opcode=b"\r") + grid()
    ).read_scene(mode="strict")
    parsed = scene.summary.line_styles[0].program
    assert parsed.kind == "extended_line_style" and not parsed.elements
    values = [e for p in parsed.parallels for e in p.elements if e.kind == "contrast"]
    assert values
    for e in values:
        assert e.length == (2.5 if unit else None)
        assert e.units == (
            "object_relative" if unit == b"oru" else "pixels" if unit else None
        )
        assert e.stretchable == (unit is None)
        assert scene.source_bytes(e.source) == prefix + b"contrast"
    assert len(scene.summary.instances) == 1
    assert all(
        e.line_style_binding.status == "complete"
        for e in scene.summary.rendering_options
    )


@pytest.mark.parametrize("mode", [b"center", b"stretch"])
@pytest.mark.parametrize("separator", [b"=", b" = ", b"\t=\n"])
@pytest.mark.parametrize(
    "absolute",
    [
        b"absolute",
        b"absolute weight",
        b"absolute length",
        b"absolute weight, absolute length",
    ],
)
def test_fit_and_absolute_options_are_scoped_per_parallel(mode, separator, absolute):
    fit = b"fit" + separator + mode
    program = (
        b"dash, parallel, -2 px offset, 3 pixels fixed weight, "
        + fit
        + b", "
        + absolute
        + b", segmented, 2 px contrast, 1 px blank"
    )
    scene = read(definition(program=program) + use()).read_scene(mode="strict")
    parsed = scene.summary.line_styles[0].program
    a, b = parsed.parallels
    assert a.fit is a.absolute_length_source is a.absolute_weight_source is None
    assert isinstance(b.fit, ed.LineStyleFit)
    assert b.fit.mode == mode.decode()
    assert scene.source_bytes(b.fit.source) == fit
    assert scene.source_bytes(b.fit.value_source) == mode
    assert bool(b.absolute_length_source) == (absolute != b"absolute weight")
    assert bool(b.absolute_weight_source) == (absolute != b"absolute length")
    if absolute == b"absolute":
        assert b.absolute_length_source == b.absolute_weight_source
    for source in (b.absolute_length_source, b.absolute_weight_source):
        if source:
            assert scene.source_bytes(source).startswith(b"absolute")
    assert b.weight.value == 3 and b.weight.fixed
    assert (
        parsed.transformed_source is None and parsed.interpretation_status == "complete"
    )
    with pytest.raises(FrozenInstanceError):
        b.fit.mode = "other"


@pytest.mark.parametrize(
    "program",
    [
        b"dash, transformed",
        b"fit=stretch, absolute, 2 px contrast, 1 px blank, transformed",
        b"dash, parallel, -2 px offset, contrast, transformed",
    ],
)
def test_transformed_is_global_and_requires_unresolved_geometry_options(program):
    doc = read(definition(program=program) + use() + grid())
    scene = doc.read_scene()
    d = scene.summary.line_styles[0]
    p = d.program
    assert scene.source_bytes(p.transformed_source) == b"transformed"
    assert not scene.source_bytes(p.parallels[-1].source).endswith(b"transformed")
    assert p.reason == d.reason == "hsf.line_style_geometry_options"
    assert d.interpretation_status == p.interpretation_status == "unsupported"
    assert (
        scene.summary.rendering_options[0].line_style_binding.reason
        == "hsf.line_style_program"
    )
    assert not scene.summary.instances and len(scene.summary.meshes) == 1
    with pytest.raises(ed.UnsupportedFeatureError) as error:
        doc.read_scene(mode="strict")
    assert error.value.diagnostic.code == "hsf.line_style_definition"
    # Even an unused unresolved definition must not silently enable placements.
    assert not read(definition(program=program) + grid()).read_scene().summary.instances


def test_explicit_absolute_does_not_supply_missing_weight_units():
    for suffix in (b"", b", transformed"):
        s = read(
            definition(program=b"1.5 weight, absolute weight, dash" + suffix)
        ).read_scene()
        p = s.summary.line_styles[0].program
        assert p.reason == "hsf.line_style_weight_units"
        assert p.parallels[0].weight.units is None
        assert p.parallels[0].absolute_weight_source is not None
        assert bool(p.transformed_source) == bool(suffix)


@pytest.mark.parametrize(
    "program",
    [
        b"fit",
        b"fit=other, dash",
        b"fit=, dash",
        b"fit=center stretch, dash",
        b"fit=center=, dash",
        b"FIT=center, dash",
        b"fit=Center, dash",
        b"fit=center, fit=stretch, dash",
        b"dash, fit=center",
        b"absolute",
        b"absolute weight length, dash",
        b"absolute=weight, dash",
        b"dash, absolute",
        b"absolute, absolute length, dash",
        b"absolute weight, absolute, dash",
        b"absolute length, absolute length, dash",
        b"transformed",
        b"transformed, dash",
        b"dash, transformed, transformed",
        b"dash, transformed, parallel, dash",
        b"dash, parallel, transformed",
        b"fit=center, parallel, dash",
        b"fit=center, 0 px contrast",
        b"-1 px contrast",
        b"inf px contrast",
        b"1 unknown contrast",
        b"contrast, garbage",
        b"2 px crosshairs",
        b"join, dash",
    ],
)
def test_invalid_or_unsupported_clauses_never_return_a_successful_prefix(program):
    doc = read(definition(program=program) + grid())
    scene = doc.read_scene()
    d = scene.summary.line_styles[0]
    assert d.program is None and d.reason == "hsf.line_style_program"
    assert scene.source_bytes(d.definition.source) == program
    assert not scene.summary.instances
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.read_scene(mode="strict")


@pytest.mark.parametrize("version", ["14.50", "19.10"])
@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
def test_forward_definition_style_include_cli_and_source_ownership(
    version, wrapper, zip_factory, tmp_path
):
    program = b"fit = center, absolute length, 2 px contrast, 1 px blank"
    body = (
        opened(b"style")
        + use()
        + b")"
        + opened(b"part")
        + styled(b"/style")
        + grid()
        + b")"
        + opened(b"placed")
        + named(b"<", b"/part")
        + b")"
        + definition(program=program)
    )
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    data = data.replace(b"V19.10", b"V" + version.encode(), 1)
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    d = scene.summary.line_styles[0]
    assert scene.summary.instances
    assert all(
        i.display.line_pattern.value.binding.definition_id == d.id
        for i in scene.summary.instances
    )
    assert doc.read_drawing().summary.scene.line_styles == scene.summary.line_styles
    assert scene.summary.style_resolutions[0].status == "complete"
    del doc
    assert scene.source_bytes(d.program.parallels[0].fit.value_source) == b"center"
    path = tmp_path / "options.hsf"
    path.write_bytes(data)
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path), "--mode", "strict"],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(run.stdout)["line_styles"] == [d.to_dict()]


def test_limits_cover_options_and_global_suffix():
    body = definition(program=b"fit=center, absolute, contrast, transformed")
    s = read(body).read_scene().summary
    with pytest.raises(ed.LimitExceededError):
        read(
            body, limits=ed.Limits(max_output_bytes=s.usage.output_bytes - 1)
        ).read_scene()
    program = b", ".join([b"contrast"] * 256 + [b"transformed"])
    with pytest.raises(ed.LimitExceededError) as error:
        read(definition(program=program)).read_scene()
    assert error.value.diagnostic.code == "hsf.limit_line_style_elements"
