"""Independent wire/expected-value tests for local > style > instance parent."""

import gc
import io
import json
import struct
import subprocess
import sys
import zipfile
from dataclasses import FrozenInstanceError

import edrawings_kit as ed
import pytest
from test_continuation import grid, texture
from test_display import size, visibility
from test_rendering import H
from test_segment_style import named, opened
from test_user_data_audit import sample
from test_views import POINTS, PROFILE, compressed, raw


def rgb(mask, value):
    return b"~" + bytes([mask]) + bytes(value)


def styled(path):
    return named(b"{", path)


def doc(body, **kwargs):
    return ed.read(raw(body + b"\0"), **kwargs)


def precedence_body():
    return (
        rgb(1, (1, 2, 3))
        + size(-7, 4)
        + opened(b"library")
        + visibility(1, 0)
        + opened(b"base")
        + rgb(1, (4, 5, 6))
        + b"q))"
        + opened(b"style")
        + styled(b"/library/base")
        + size(-2, 3)
        + b")"
        + opened(b"part")
        + styled(b"/style")
        + grid()
        + opened(b"child")
        + rgb(1, (10, 11, 12))
        + grid()
        + b"))"
        # Reopening a tagged source after references updates all styled users.
        + b"s\0\0\0\0"
        + rgb(1, (7, 8, 9))
        + b")"
    )


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed", "compressed"])
def test_precedence_nested_styles_final_source_and_lifetime(wrapper):
    body = precedence_body()
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    if wrapper in ("zip", "prefixed"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("eModel", data)
        data = stream.getvalue()
        if wrapper == "prefixed":
            from conftest import PREFIX

            data = PREFIX + data
    document = ed.read(data)
    result = document.read_scene(mode="strict")
    del document
    gc.collect()
    s = result.summary
    assert s.status == s.placement_status == "complete"
    assert not s.diagnostics and len(s.instances) == 2
    assert len(s.style_resolutions) == 2
    assert all(x.interpretation_status == "complete" for x in s.style_segments)
    assert s.nodes[4].display.colors[0] is None  # raw local state stays raw
    for resolution in s.style_resolutions:
        assert isinstance(resolution, ed.StyleResolution)
        assert resolution.status == "complete" and resolution.reason is None
        assert resolution.display.colors[0].value == (7, 8, 9)
        assert resolution.display.visibility[0] is None  # no style-parent leak
        assert resolution.display.marker_size.value == ed.MarkerSize(2, "points")
        with pytest.raises(FrozenInstanceError):
            resolution.status = "unsupported"
    for instance, value in zip(s.instances, [(7, 8, 9), (10, 11, 12)], strict=True):
        assert instance.face_color.value == instance.display.colors[0].value == value
        assert instance.face_color.source == instance.display.colors[0].source
        assert result.source_bytes(instance.face_color.source) == rgb(1, value)
        assert instance.face_visible is None
        assert instance.display.marker_size.value == ed.MarkerSize(2, "points")


def test_include_uses_instance_parent_and_style_never_includes_geometry():
    body = (
        rgb(1, (1, 1, 1))
        + visibility(1, 1)
        + opened(b"style")
        + size(-3, 4)
        + b"l"
        + POINTS
        + b")"
        + opened(b"model")
        + styled(b"/style")
        + grid()
        + b")"
        + opened(b"red")
        + rgb(1, (255, 0, 0))
        + named(b"<", b"/model")
        + b")"
        + opened(b"blue")
        + rgb(1, (0, 0, 255))
        + visibility(1, 0)
        + named(b"<", b"/model")
        + b")"
    )
    s = doc(body).read_scene(mode="strict").summary
    assert len(s.instances) == 3 and len(s.primitive_instances) == 1
    assert [x.face_color.value for x in s.instances] == [
        (1, 1, 1),
        (255, 0, 0),
        (0, 0, 255),
    ]
    assert [x.face_visible.value for x in s.instances] == [True, True, False]
    assert all(
        x.display.marker_size.value == ed.MarkerSize(3, "pixels") for x in s.instances
    )
    assert s.style_resolutions[0].display.colors[0] is None


@pytest.mark.parametrize("version", ["8.05", "14.50", "19.10"])
def test_multiple_styles_can_supply_distinct_geometry_bits(version):
    body = (
        opened(b"face")
        + rgb(1, (1, 2, 3))
        + visibility(1, 1)
        + b")"
        + opened(b"line")
        + rgb(4, (4, 5, 6))
        + visibility(4, 0)
        + b")"
        + styled(b"/face")
        + styled(b"/line")
        + b"l"
        + POINTS
        + b"\0"
    )
    s = (
        ed.read(f";; HSF V{version} \n".encode() + body)
        .read_scene(mode="strict")
        .summary
    )
    d = s.primitive_instances[0].display
    assert d.colors[0].value == (1, 2, 3) and d.colors[2].value == (4, 5, 6)
    assert d.visibility[0].value is True and d.visibility[2].value is False


def test_style_matrix_is_unsupported_but_owner_matrix_is_preserved():
    matrix = b"%" + struct.pack("<12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, 10, 0, 0)
    s = doc(opened(b"a") + matrix + b")" + styled(b"/a") + grid()).read_scene().summary
    assert s.style_resolutions[0].reason == "hsf.style_target_attributes"
    s = (
        doc(opened(b"a") + rgb(1, (1, 2, 3)) + b")" + styled(b"/a") + matrix + grid())
        .read_scene(mode="strict")
        .summary
    )
    assert s.instances[0].world_transform[12] == 10
    assert s.instances[0].display.colors[0].value == (1, 2, 3)


def test_disjoint_styles_and_local_override_including_root_and_extended_masks():
    body = (
        opened(b"a")
        + rgb(1, (1, 2, 3))
        + b")"
        + opened(b"b")
        + visibility(0x03FFFFFF, 0x01000201)
        + b"="
        + struct.pack("<fB", -2, 4)
        + b"\x0e"
        + struct.pack("<fB", -4, 3)
        + b")"
    )
    body += styled(b"/a") + styled(b"/b") + rgb(1, (9, 8, 7)) + grid()
    result = doc(body).read_scene(mode="strict")
    s = result.summary
    instance = s.instances[0]
    assert instance.face_color.value == (9, 8, 7)
    assert instance.face_visible.value is True
    assert instance.display.visibility[24].value is True
    assert instance.display.visibility[9].value is True
    assert instance.display.line_weight.value == ed.MarkerSize(2, "pixels")
    assert instance.display.edge_weight.value == ed.MarkerSize(4, "points")
    assert len(s.style_resolutions[0].style_ids) == 2


@pytest.mark.parametrize(
    "attribute",
    [
        rgb(1, (1, 2, 3)),
        visibility(1, 1),
        size(1),
        b"=" + struct.pack("<f", 2),
        b"\x0e" + struct.pack("<f", 3),
    ],
)
def test_conflicting_styles_never_choose_by_insertion_order(attribute):
    body = (
        opened(b"a")
        + attribute
        + b")"
        + opened(b"b")
        + attribute
        + b")"
        + styled(b"/a")
        + styled(b"/b")
        + grid()
    )
    d = doc(body)
    s = d.read_scene().summary
    r = s.style_resolutions[0]
    assert r.status == "unsupported" and r.reason == "hsf.style_conflict"
    assert r.display is None and not s.instances
    with pytest.raises(ed.UnsupportedFeatureError) as exc:
        d.read_scene(mode="strict")
    assert exc.value.diagnostic.code == r.reason
    diagnostic = exc.value.diagnostic
    source = s.style_segments[0].source
    assert (
        diagnostic.domain_id,
        diagnostic.byte_range.offset,
        diagnostic.byte_range.length,
    ) == (source.domain_id, source.offset, source.length)


@pytest.mark.parametrize("condition", [b"", b"on", b"\xff"])
def test_conditions_are_not_assumed_true_or_false(condition):
    d = doc(
        opened(b"a")
        + rgb(1, (1, 2, 3))
        + b")"
        + b"{\0\x02/a"
        + bytes([len(condition)])
        + condition
        + grid()
    )
    s = d.read_scene().summary
    assert s.style_resolutions[0].reason == "hsf.style_condition"
    assert not s.instances


@pytest.mark.parametrize(
    "body,reason",
    [
        (styled(b"/missing"), "hsf.style_unresolved"),
        (styled(b"/later") + opened(b"later") + b")", "hsf.style_unresolved"),
        (styled(b"/"), "hsf.style_cycle"),
        (
            opened(b"a")
            + b")"
            + opened(b"b")
            + styled(b"/a")
            + b")"
            + opened(b"a")
            + styled(b"/b")
            + b")",
            "hsf.style_cycle",
        ),
        (opened(b"a") + H + b")" + styled(b"/a"), "hsf.style_target_attributes"),
        (
            opened(b"a") + texture() + b")" + styled(b"/a"),
            "hsf.style_target_attributes",
        ),
        (opened(b"a") + b"h\x01)" + styled(b"/a"), "hsf.style_target_attributes"),
        (opened(b"a") + b")" + styled(b"/a") + H, "hsf.style_target_attributes"),
    ],
)
def test_unknown_effects_remain_closed(body, reason):
    s = doc(body + grid()).read_scene().summary
    assert s.style_resolutions and all(r.reason == reason for r in s.style_resolutions)
    assert not s.instances and s.placement_status == "unsupported"
    assert all(r.display is None for r in s.style_resolutions)


@pytest.mark.parametrize("stop", [b"\xff", opened(b"../outside") + b")"])
def test_truncated_scene_cannot_publish_final_style_values(stop):
    s = (
        doc(opened(b"a") + rgb(1, (1, 2, 3)) + b")" + styled(b"/a") + stop)
        .read_scene()
        .summary
    )
    assert s.style_resolutions[0].reason == "hsf.style_incomplete_scene"
    assert s.style_resolutions[0].display is None
    assert not s.instances


def test_private_data_and_import_context_still_withhold_placements():
    body = opened(b"a") + rgb(1, (1, 2, 3)) + b")" + styled(b"/a") + grid()
    s = doc(body).read_scene(import_root="/import").summary
    assert s.style_resolutions[0].status == "unsupported"  # /a is not /import/a
    s = doc(body).read_scene(import_root="/").summary
    assert s.style_resolutions[0].status == "complete"
    assert not s.instances and s.placement_status == "unsupported"
    d = ed.read(compressed(sample() + b"h\0" + body + b"z"))
    s = d.read_scene(user_data_profile=PROFILE).summary
    assert s.style_resolutions[0].status == "complete"
    assert (
        s.opaque_user_data and not s.instances and s.placement_status == "unsupported"
    )


def chain(count):
    body = opened(b"n0") + rgb(1, (1, 2, 3)) + b")"
    for i in range(1, count):
        body += opened(f"n{i}".encode()) + styled(f"/n{i - 1}".encode()) + b")"
    return body + styled(f"/n{count - 1}".encode()) + grid()


def test_visit_budget_shared_with_instance_traversal():
    # One style edge + one tree edge + one geometry: a single shared budget.
    body = opened(b"a") + rgb(1, (1, 2, 3)) + b")" + styled(b"/a") + grid()
    d = doc(body, limits=ed.Limits(max_scene_visits=2))
    with pytest.raises(ed.LimitExceededError) as exc:
        d.read_scene()
    assert exc.value.diagnostic.code == "hsf.limit_scene_visits"
    assert (
        doc(body, limits=ed.Limits(max_scene_visits=3)).read_scene().summary.status
        == "complete"
    )


def test_cached_style_chain_cannot_bypass_depth_limit():
    body = chain(8)
    with pytest.raises(ed.LimitExceededError) as exc:
        doc(body, limits=ed.Limits(max_scene_depth=8)).read_scene()
    assert exc.value.diagnostic.code == "hsf.limit_scene_depth"
    assert (
        doc(body, limits=ed.Limits(max_scene_depth=9)).read_scene().summary.status
        == "complete"
    )


def test_cli_and_drawing_status(tmp_path):
    data = raw(precedence_body() + b"\0")
    path = tmp_path / "styles.hsf"
    path.write_bytes(data)
    s = ed.read_file(path, read_metadata=False).read_scene(mode="strict").summary
    output = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path), "--mode", "strict"],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert json.loads(output.stdout) == s.to_dict()
    drawing = ed.read(data).read_drawing().summary
    assert drawing.scene.placement_status == "complete"
    assert drawing.assessment.status == "partial"
