"""Explicit import namespaces are caller evidence, never verified placements."""

import gc
import json
import subprocess
import sys

import edrawings_kit as ed
import pytest
from test_continuation import grid
from test_segment_style import named, opened
from test_terminal_user_data import PROFILE, make
from test_views import compressed, raw


def test_default_retains_root_stop_and_context_enables_external_sibling():
    body = (
        b"h\0"
        + opened(b"a/b")
        + opened(b"../../../shared")
        + grid()
        + b")"
        + named(b"<", b"../../../shared")
        + b")"
    )
    doc = ed.read(raw(body + b"\0"))
    default = doc.read_scene().summary
    assert default.import_context is None and default.processed_records == 2
    assert default.diagnostics[-1].code == "hsf.segment_path" and not default.meshes
    scene = doc.read_scene(import_root="/import")
    s = scene.summary
    assert s.processed_records == len(s.hsf.records) and len(s.meshes) == 1
    assert s.references[0].target_id == s.nodes[-1].id
    assert s.nodes[-1].parent_id == s.nodes[0].id  # global sibling of import
    assert s.nodes[0].world_handedness is None
    assert s.nodes[1].world_handedness.value == "left"
    assert s.placement_status == "unsupported" and not s.instances
    assert [d.code for d in s.diagnostics] == ["hsf.import_context"]
    assert (
        s.diagnostics[0].severity == "warning" and s.diagnostics[0].byte_range is None
    )
    assert scene.source_bytes(s.nodes[-1].name_source) == b"../../../shared"


@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
def test_context_metadata_source_absence_normalization_and_lifetime(
    wrapper, zip_factory
):
    body = opened(b"../shared") + grid() + b")"
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(import_root="/ Host /  My   Import ")
    del doc
    gc.collect()
    s = scene.summary
    c = s.import_context
    assert isinstance(c, ed.SceneImportContext)
    assert c.requested_root == "/ Host /  My   Import "
    assert c.resolved_root == "/host/my import" and c.node_id == s.nodes[2].id
    assert c.context_node_ids == tuple(n.id for n in s.nodes[:3])
    assert c.interpretation_status == "unsupported"
    assert all(n.source is None and n.name_source is None for n in s.nodes[:3])
    assert s.nodes[-1].parent_id == s.nodes[1].id
    assert scene.source_bytes(s.nodes[-1].name_source) == b"../shared"
    assert scene.mesh_buffers(s.meshes[0].id).vertices.shape == (6, 3)


@pytest.mark.parametrize("root", ["/", "/import", "/parent/import"])
def test_explicit_context_is_partial_even_when_no_escape_is_used(root):
    doc = ed.read(raw(grid() + b"\0"))
    assert doc.read_scene(mode="strict").summary.placement_status == "complete"
    scene = doc.read_scene(import_root=root)
    assert scene.summary.status == "partial" and not scene.summary.instances
    with pytest.raises(ed.UnsupportedFeatureError) as err:
        doc.read_scene(mode="strict", import_root=root)
    assert err.value.diagnostic.code == "hsf.import_context"


def test_context_does_not_rebase_absolute_paths_or_standard_aliases():
    body = opened(b"/shared") + b")" + opened(b"../shared") + b")"
    s = ed.read(raw(body + b"\0")).read_scene(import_root="/import").summary
    assert len(s.nodes) == 3
    assert s.nodes[-1].parent_id == s.nodes[0].id
    alias = (
        ed.read(raw(opened(b"?Home/shared") + b")\0"))
        .read_scene(import_root="/import")
        .summary
    )
    assert len(alias.nodes) == 3 and alias.nodes[-1].parent_id == alias.nodes[0].id
    assert alias.segment_aliases[0].target_path == "/"


def test_context_does_not_clamp_beyond_global_root_or_load_missing_targets():
    doc = ed.read(raw(opened(b"../../outside") + grid() + b")\0"))
    s = doc.read_scene(import_root="/import").summary
    assert not s.meshes and s.processed_records == 0
    assert s.diagnostics[-1].code == "hsf.segment_path"
    missing = (
        ed.read(raw(named(b"<", b"../missing") + b"\0"))
        .read_scene(import_root="/import")
        .summary
    )
    assert missing.references[0].target_id is None and len(missing.nodes) == 2
    assert missing.diagnostics[-1].code == "hsf.unresolved_reference"


@pytest.mark.parametrize(
    "root",
    [
        "",
        "relative",
        "//a",
        "/a/",
        "/a//b",
        "/a/ ",
        "/.",
        "/..",
        "/...",
        "/....",
        "/a/../b",
        "/a/^",
        "/?Home",
        "/a/*",
        "/a,b",
        "/a/(b)",
        "/'a'",
        '/"a"',
        "/`a`",
        "/a\tb",
        "/a\0b",
        "/a\\b",
        "/日本語",
        "/" + "a" * 4096,
    ],
)
def test_invalid_context_paths_are_errors_in_both_modes(root):
    for mode in ("partial", "strict"):
        with pytest.raises(ed.InvalidFormatError) as err:
            ed.read(raw(b"\0")).read_scene(import_root=root, mode=mode)
        assert err.value.diagnostic.code == "hsf.invalid_import_root"


@pytest.mark.parametrize(
    "limits,code",
    [
        ({"max_scene_nodes": 2}, "hsf.limit_scene_nodes"),
        ({"max_scene_depth": 2}, "hsf.limit_scene_depth"),
        ({"max_output_bytes": 0}, "limits.output_bytes"),
    ],
)
def test_context_ancestors_count_against_limits(limits, code):
    with pytest.raises(ed.LimitExceededError) as err:
        ed.read(raw(b"\0"), limits=ed.Limits(**limits)).read_scene(import_root="/a/b")
    assert err.value.diagnostic.code == code


def test_first_and_terminal_user_data_keep_import_scope_authorization():
    # The encoded root scope is the import location, not necessarily database /.
    doc = ed.read(make(46, "19.10"))
    s = doc.read_scene(user_data_profile=PROFILE, import_root="/host/import").summary
    assert len(s.opaque_user_data) == 2 and s.processed_records == len(s.hsf.records)
    assert s.import_context.node_id == s.nodes[2].id
    assert s.placement_status == "unsupported"
    default = doc.read_scene(import_root="/host/import").summary
    assert not default.opaque_user_data and default.hsf.unparsed


@pytest.mark.parametrize("command", ["scene", "drawing"])
def test_cli_context_agrees_with_python_and_strict_rejection(tmp_path, command):
    path = tmp_path / "external.hsf"
    path.write_bytes(raw(opened(b"../shared") + grid() + b")\0"))
    arguments = [
        sys.executable,
        "-m",
        "edrawings_kit",
        command,
        str(path),
        "--import-root",
        "/import",
    ]
    run = subprocess.run(arguments, capture_output=True, encoding="utf-8", check=True)
    result = getattr(ed.read_file(path, read_metadata=False), "read_" + command)(
        import_root="/import"
    )
    assert json.loads(run.stdout) == result.summary.to_dict()
    strict = subprocess.run(
        arguments + ["--mode", "strict"], capture_output=True, encoding="utf-8"
    )
    assert strict.returncode == 2 and not strict.stdout
    assert json.loads(strict.stderr)["error"]["code"] == "hsf.import_context"


def test_new_context_does_not_mutate_document_or_other_calls():
    doc = ed.read(raw(opened(b"../shared") + b")\0"))
    before = doc.read_scene().summary
    a = doc.read_scene(import_root="/import").summary
    b = doc.read_scene(import_root="/host/import").summary
    assert doc.read_scene().summary == before
    assert a.nodes[-1].parent_id == a.nodes[0].id
    assert b.nodes[-1].parent_id == b.nodes[1].id


def test_anonymous_children_include_context_ancestors_in_depth_limit():
    with pytest.raises(ed.LimitExceededError) as err:
        ed.read(raw(b"(\0)\0"), limits=ed.Limits(max_scene_depth=2)).read_scene(
            import_root="/import"
        )
    assert err.value.diagnostic.code == "hsf.limit_scene_depth"
