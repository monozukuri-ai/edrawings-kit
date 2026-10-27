"""Texture expression and local/Style image identity, without rendered claims."""

import gc
import json
import struct
import subprocess
import sys
from dataclasses import FrozenInstanceError

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_image_scene import picture
from test_images import IMAGE, JPEG
from test_segment_style import named, opened
from test_style_resolution import styled
from test_views import compressed, raw


def color(
    expression=b"diffuse color=`r=0.25 g=0.5 b=1`,diffuse texture=(tile)", mask=1
):
    length = (
        bytes([len(expression)])
        if len(expression) < 255
        else b"\xff" + struct.pack("<i", len(expression))
    )
    return b'"' + bytes([mask, 1]) + length + expression


def definition(name=b"tile", source=b"tile"):
    return (
        b"t" + bytes([len(name)]) + name + bytes([len(source)]) + source + b"\x01\0\x01"
    )


def read(body, **kwargs):
    return ed.read(raw(body + b"\0"), **kwargs).read_scene(image_profile=IMAGE)


def styled_body():
    # Forward image source, two nested styles, and no accidental geometry import.
    return (
        opened(b"library")
        + definition()
        + b")"
        + opened(b"middle")
        + styled(b"/library")
        + b")"
        + opened(b"part")
        + styled(b"/middle")
        + color()
        + grid()
        + b")"
        + opened(b"library")
        + picture()
        + b")"
    )


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed", "compressed"])
def test_nested_style_scope_forward_image_source_and_lifetime(wrapper, zip_factory):
    body = styled_body()
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(image_profile=IMAGE)
    del doc
    gc.collect()
    s = scene.summary
    assert len(s.texture_uses) == 1
    u = s.texture_uses[0]
    assert isinstance(u, ed.TextureUse) and isinstance(u.binding, ed.TextureBinding)
    assert isinstance(u.diffuse_color, ed.FloatColorAttribute)
    assert u.node_id == s.nodes[3].id and u.geometry_mask == 1
    assert scene.source_bytes(u.source) == color()
    assert scene.source_bytes(u.texture_name.source) == b"tile"
    assert scene.source_bytes(u.diffuse_color.source) == b"r=0.25 g=0.5 b=1"
    assert u.diffuse_color.value == (0.25, 0.5, 1)
    b = u.binding
    assert b.scope == "local_and_styles" and b.status == "complete" and b.reason is None
    assert b.image_id == s.images[0].id
    assert b.texture_definition_ids == (s.textures[0].id,)
    assert b.style_path == (s.style_segments[1].id, s.style_segments[0].id)
    assert scene.source_bytes(s.images[0].data_source) == JPEG
    assert s.status == "partial" and s.placement_status == "unsupported"
    assert u.interpretation_status == "unsupported"
    assert not s.instances and not s.primitive_instances
    assert s.style_resolutions[0].status == "unsupported"
    with pytest.raises(FrozenInstanceError):
        b.status = "unsupported"


@pytest.mark.parametrize(
    "expression,expected",
    [
        (b"diffuse texture=tile", None),
        (b" DIFFUSE  TEXTURE = (tile) ", None),
        (b"diffuse color=(r=1e-1 g=0.0 b=1), diffuse texture=tile", (0.1, 0, 1)),
    ],
)
def test_supported_whole_expressions(expression, expected):
    u = read(picture() + color(expression, mask=5)).summary.texture_uses[0]
    assert u.binding.status == "complete" and u.geometry_mask == 5
    assert not u.binding.style_path and not u.binding.texture_definition_ids
    if expected is None:
        assert u.diffuse_color is None
    else:
        assert u.diffuse_color.value == pytest.approx(expected)


@pytest.mark.parametrize(
    "expression",
    [
        b"diffuse texture=",
        b"diffuse texture=(tile,other)",
        b"diffuse texture=(tile) trailing",
        b"diffuse texture='tile'",
        b"diffuse texture=(tile),diffuse texture=other",
        b"diffuse texture=(a/b)",
        b"diffuse texture=(tile\0)",
        b"diffuse texture=(\xff)",
        b"diffuse texture=../../secret",
        b"diffuse texture=(tile*other)",
        b"diffuse color=`r=nan g=0 b=0`,diffuse texture=tile",
        b"diffuse color=`r=2 g=0 b=0`,diffuse texture=tile",
        b"diffuse color=`r=1g=0 b=0`,diffuse texture=tile",
        b"diffuse texture=tile" + b" " * 4096,
    ],
)
def test_unknown_expression_retains_whole_source_without_partial_binding(expression):
    scene = read(color(expression) + picture())
    u = scene.summary.texture_uses[0]
    assert scene.source_bytes(u.specification.source) == expression
    assert u.texture_name is None and u.diffuse_color is None
    assert u.binding.reason == "hsf.texture_expression" and u.binding.image_id is None
    assert scene.summary.processed_records == len(scene.summary.hsf.records)


@pytest.mark.parametrize(
    "body,reason",
    [
        (picture() + picture(), "hsf.texture_ambiguous_image"),
        (definition() + definition() + picture(), "hsf.texture_ambiguous_definition"),
        (definition(source=b"other") + picture(), "hsf.texture_definition_source"),
        (
            definition() + opened(b"elsewhere") + picture() + b")",
            "hsf.texture_image_scope",
        ),
        (opened(b"elsewhere") + picture() + b")", "hsf.texture_parent_context"),
        (picture(name=b"TILE"), "hsf.texture_name_semantics"),
        (picture() + definition(name=b"TILE"), "hsf.texture_name_semantics"),
        (
            opened(b"a") + picture() + b")" + b"{\0\x02/a\0",
            "hsf.texture_style_condition",
        ),
        (styled(b"/missing"), "hsf.texture_style_unresolved"),
        (styled(b"/"), "hsf.texture_style_cycle"),
        (
            opened(b"a")
            + picture()
            + b")"
            + opened(b"b")
            + picture()
            + b")"
            + styled(b"/a")
            + styled(b"/b"),
            "hsf.texture_style_conflict",
        ),
    ],
)
def test_lookup_refuses_ambiguous_or_unknown_scope(body, reason):
    s = read(body + color()).summary
    u = s.texture_uses[0]
    assert u.binding.reason == reason and u.binding.status == "unsupported"
    assert u.binding.image_id is None and not u.binding.style_path
    assert not s.instances


def test_local_image_shadows_styles_and_parent_is_not_an_include_context():
    body = opened(b"style") + picture() + b")" + styled(b"/style") + picture() + color()
    s = read(body).summary
    assert s.texture_uses[0].binding.image_id == s.images[1].id
    assert not s.texture_uses[0].binding.style_path
    # Parent resources can differ across include paths, so this lookup abstains.
    s = read(picture() + opened(b"child") + color() + b")").summary
    assert s.texture_uses[0].binding.reason == "hsf.texture_parent_context"


def test_style_target_parents_and_geometry_include_edges_are_not_searched():
    body = opened(b"parent") + picture() + opened(b"style") + b"))"
    s = read(body + styled(b"/parent/style") + color()).summary
    assert s.texture_uses[0].binding.reason == "hsf.texture_parent_context"
    s = read(opened(b"a") + picture() + b")" + named(b"<", b"/a") + color()).summary
    assert s.texture_uses[0].binding.reason == "hsf.texture_parent_context"


@pytest.mark.parametrize("suffix", [b"\xff", opened(b"../outside") + b")"])
def test_incomplete_scene_never_returns_a_final_resource_association(suffix):
    s = read(picture() + color() + suffix).summary
    assert s.texture_uses[0].binding.reason == "hsf.texture_incomplete_scene"
    assert s.texture_uses[0].binding.image_id is None


def test_ordered_color_requests_are_not_claimed_as_active_materials():
    s = read(
        picture() + color() + color(b"diffuse texture=missing") + b"~\x01\xff\0\0"
    ).summary
    assert len(s.texture_uses) == 2
    assert s.texture_uses[0].binding.status == "complete"
    assert s.texture_uses[1].binding.status == "unsupported"
    assert s.nodes[0].display.colors[0].value == (255, 0, 0)
    assert all(x.interpretation_status == "unsupported" for x in s.texture_uses)


def test_plain_colors_are_not_guessed_as_texture_names():
    assert not read(
        picture() + color(b"tile") + color(b"red") + color(b"texturelike")
    ).summary.texture_uses


def test_limits_and_context_are_preserved():
    body = picture() + color() + color()
    with pytest.raises(ed.LimitExceededError) as exc:
        read(body, limits=ed.Limits(max_scene_visits=1))
    assert exc.value.diagnostic.code == "hsf.limit_scene_visits"
    assert all(
        u.binding.status == "complete"
        for u in read(body, limits=ed.Limits(max_scene_visits=2)).summary.texture_uses
    )
    with pytest.raises(ed.LimitExceededError):
        read(body, limits=ed.Limits(max_output_bytes=50_000))
    scene = ed.read(raw(picture() + color() + b"\0")).read_scene(
        image_profile=IMAGE, import_root="/import"
    )
    assert scene.summary.texture_uses[0].binding.status == "complete"
    assert scene.summary.placement_status == "unsupported"


def test_cli_matches_native_model_and_drawing_remains_partial(tmp_path):
    path = tmp_path / "texture.hsf"
    path.write_bytes(raw(styled_body() + b"\0"))
    document = ed.read_file(path, read_metadata=False)
    scene = document.read_scene(image_profile=IMAGE)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "edrawings_kit",
            "scene",
            str(path),
            "--image-profile",
            IMAGE,
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(result.stdout) == scene.summary.to_dict()
    drawing = document.read_drawing(image_profile=IMAGE).summary
    assert drawing.scene.texture_uses == scene.summary.texture_uses
    assert drawing.assessment.status == "partial"
