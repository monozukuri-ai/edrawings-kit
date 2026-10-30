"""Alias assumptions and unsupported style effects withhold placements."""

import gc
import json
import subprocess
import sys
import zlib

import edrawings_kit as ed
import pytest
from test_continuation import grid, texture
from test_views import raw


def named(opcode, path):
    return opcode + bytes([len(path)]) + path


def opened(path):
    return named(b"(", path)


@pytest.mark.parametrize(
    "alias,target",
    [
        (b"?Home", "/"),
        (b"?Include Library", "/include library"),
        (b"?Style Library", "/style library"),
    ],
)
@pytest.mark.parametrize("compressed", [False, True])
def test_alias_inventory_and_lifetime(alias, target, compressed):
    body = opened(alias + b"/Part") + grid() + b")" + opened(alias + b"/part") + b")"
    data = raw(
        b"Z" + zlib.compress(body + b"z") + b"\0" if compressed else body + b"\0"
    )
    doc = ed.read(data)
    scene = doc.read_scene()
    with pytest.raises(ed.UnsupportedFeatureError) as exc:
        doc.read_scene(mode="strict")
    assert exc.value.diagnostic.code == "hsf.segment_alias_default"
    del doc
    gc.collect()
    s = scene.summary
    assert s.processed_records == len(s.hsf.records)
    assert len(s.segment_aliases) == len(s.meshes) == 1
    assert s.status == "partial" and s.placement_status == "unsupported"
    assert not s.instances and not s.primitive_instances
    a = s.segment_aliases[0]
    assert isinstance(a, ed.SegmentAlias)
    assert a.alias == alias.decode() and a.target_path == target
    assert a.interpretation_status == "unsupported"
    r = next(r for r in s.hsf.records if r.id == a.source_record_id)
    assert r.source == a.source and scene.source_bytes(a.source) == opened(
        alias + b"/Part"
    )
    assert [d.code for d in s.diagnostics] == ["hsf.segment_alias_default"]
    assert s.diagnostics[0].severity == "warning"


def test_literal_case_spaces_parent_and_alias_share_identity():
    body = (
        opened(b"/Include Library/MY  Part")
        + b")"
        + opened(b"?include   LIBRARY/ my part ")
        + b")"
        + opened(b"/include library/child")
        + opened(b"^/MY PART")
        + b"))"
    )
    s = ed.read(raw(body + b"\0")).read_scene().summary
    assert len(s.nodes) == 4  # root, library, part, child
    assert len(s.segment_aliases) == 1
    assert s.processed_records == len(s.hsf.records)
    assert s.nodes[2].name == "/Include Library/MY  Part"  # raw spelling survives
    literal = ed.read(raw(opened(b"/A/B") + b")" + opened(b"/a/ b ") + grid() + b")\0"))
    strict = literal.read_scene(mode="strict").summary
    assert len(strict.nodes) == 3 and len(strict.instances) == 1


@pytest.mark.parametrize(
    "path",
    [
        b"?custom/a",
        b"   ",
        b"/a/?Home",
        b"?Home/..",
        b"../a",
        b"../../a",
        b"/a/...",
        b"/a/....",
        b"/a/*",
        b"/a,b",
        b"/a/(b)",
        b"/a/'b'",
        b'/a/"b"',
        b"/a/\tb",
        b"/a/\\b",
        b"/a/^b",
        b"/a/\0b",
    ],
)
def test_unknown_and_external_paths_stop_without_recovery(path):
    s = ed.read(raw(opened(path) + grid() + b")\0")).read_scene().summary
    assert s.processed_records == 0 and not s.meshes and not s.instances
    assert s.diagnostics[-1].code == "hsf.segment_path"
    assert s.diagnostics[-1].severity == "error"


@pytest.mark.parametrize("condition", [None, b"flag", b"", b"\xff"])
def test_style_reference_is_not_geometry_or_inherited_attributes(condition):
    style = (
        named(b"{", b"../defs")
        if condition is None
        else (b"{\0" + bytes([7]) + b"../defs" + bytes([len(condition)]) + condition)
    )
    body = (
        opened(b"defs")
        + b"h\x01"
        + grid()
        + b")"
        + opened(b"part")
        + style
        + grid()
        + b")"
    )
    doc = ed.read(raw(body + b"\0"))
    scene = doc.read_scene()
    with pytest.raises(ed.UnsupportedFeatureError) as exc:
        doc.read_scene(mode="strict")
    assert exc.value.diagnostic.code == (
        "hsf.style_target_attributes" if condition is None else "hsf.style_condition"
    )
    s = scene.summary
    assert len(s.meshes) == 2 and not s.references and not s.instances
    assert s.processed_records == len(s.hsf.records)
    assert s.placement_status == "unsupported"
    link = s.style_segments[0]
    assert isinstance(link, ed.StyleSegmentReference)
    assert link.node_id == s.nodes[2].id and link.target_id == s.nodes[1].id
    assert s.nodes[2].world_handedness is None
    assert link.interpretation_status == "unsupported"
    assert scene.source_bytes(link.source) == style
    assert scene.source_bytes(link.path.source) == b"../defs"
    assert link.path.value == "../defs"
    if condition is None:
        assert link.condition is None
    else:
        assert scene.source_bytes(link.condition.source) == condition
        assert link.condition.value == (
            condition.decode() if condition.isascii() else None
        )
    assert s.diagnostics[-1].severity == "warning"


def test_unresolved_and_cyclic_style_edges_do_not_traverse_or_backfill():
    body = (
        named(b"{", b"/later")
        + opened(b"later")
        + named(b"{", b"/")
        + named(b"{", b".")
        + named(b"{", b"?custom")
        + b")"
        + grid()
    )
    s = ed.read(raw(body + b"\0")).read_scene().summary
    assert [x.target_id for x in s.style_segments] == [
        None,
        s.nodes[0].id,
        s.nodes[1].id,
        None,
    ]
    assert len(s.meshes) == 1 and not s.instances and not s.references
    assert s.processed_records == len(s.hsf.records)


def test_style_clears_geometry_tag_target():
    s = ed.read(raw(grid() + named(b"{", b"/") + b"qr\0\0\0\0\0")).read_scene().summary
    assert s.references[0].target_id is None
    assert [d.code for d in s.diagnostics] == [
        "hsf.unknown_tag_target",
        "hsf.unresolved_reference",
        "hsf.style_cycle",
    ]


@pytest.mark.parametrize(
    "body,maximum",
    [
        (opened(b"?Home") + b")", 0),
        (named(b"{", b"/"), 0),
        (named(b"{", b"?Home"), 1),
        (opened(b"?Home") + b")" + texture(), 1),
        (texture() + named(b"{", b"/"), 1),
        (named(b"{", b"/") + texture(), 1),
    ],
)
def test_cumulative_definition_limit(body, maximum):
    with pytest.raises(ed.LimitExceededError) as exc:
        ed.read(
            raw(body + b"\0"), limits=ed.Limits(max_scene_definitions=maximum)
        ).read_scene()
    assert exc.value.diagnostic.code == "hsf.limit_definitions"


def test_cli_preserves_alias_and_style_metadata(tmp_path):
    data = raw(
        opened(b"?Style Library/defs")
        + b")"
        + named(b"{", b"?Style Library/defs")
        + grid()
        + b"\0"
    )
    path = tmp_path / "styles.hsf"
    path.write_bytes(data)
    scene = ed.read_file(path, read_metadata=False).read_scene().summary
    output = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path)],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert json.loads(output.stdout) == scene.to_dict()
