"""Display bundles: estimated placements, bodies, colours, configurations and previews.

Fixtures are synthetic HSF streams; expected values are computed independently.
"""

import json
import struct
import subprocess
import sys

import edrawings_kit as ed
import pytest
from conftest import make_zip
from edrawings_kit import _core
from test_components import opened
from test_scene import HEADER, POINTS, assembly, shell
from test_terminal_user_data import packed, terminal
from test_user_data_audit import sample

PLAIN = {"user_data_profile": "disabled", "image_profile": "disabled"}
MOUNT = b"/include library/model_0_include"
CLIMB = b"../../../../../../../model_0_include/shared"


def unpack(buffer):
    code = {"<f4": "f", "<f8": "d", "<i4": "i", "<u4": "I", "<u1": "B"}[buffer.dtype]
    size = struct.calcsize(code)
    flat = struct.unpack(f"<{len(buffer.data) // size}{code}", buffer.data)
    if len(buffer.shape) == 2:
        return tuple(zip(*[iter(flat)] * buffer.shape[1], strict=True))
    return flat


def option(value):
    raw = value.encode("ascii")
    return b"U" + struct.pack("<H", len(raw)) + raw


def include(path):
    return b"<" + bytes([len(path)]) + path


def blob(value):
    return bytes([len(value)]) + value


def header(revision, revision_string, *, include_path=b""):
    """First eDrawings header with a chosen revision string (layout of sample())."""
    payload = (
        b"\xbe"
        + blob(b"2018-01.00")
        + blob(b"SWeModels-26.0.1.0001-2017284")
        + blob(b"")
        + blob(b"")
        + b"\x00"
        + struct.pack("<16f", *([0.0] * 16))
        + struct.pack("<I", revision)
        + b"\x01"
        + bytes(16)
        + blob(include_path)
        + blob(bytes(16))
        + blob(bytes(16))
        + blob(b"Config-12")
        + b"\x01\x00"
        + blob(revision_string)
        + b"\x00"
        + blob(bytes(24))
        + bytes(48)
    )
    delta = 1 + (not include_path)
    return b"[" + struct.pack("<I", len(payload) - delta) + payload + b"]"


def test_assembly_bundle_matches_the_verified_scene():
    data = HEADER + assembly() + b"\0"
    doc = ed.read(data)
    scene = doc.read_scene(mode="strict")
    # Two instances inherit a face-visibility-off flag: eDrawings hides them, so
    # the default bundle keeps one; include_hidden keeps all three.
    shown = doc.read_display(**PLAIN)
    assert shown.summary.instance_count == 1
    assert shown.summary.statistics.hidden_instances == 2
    assert shown.summary.statistics.hidden_bodies == 0
    assert unpack(shown.instance_buffers().visibility) == (1,)
    display = doc.read_display(include_hidden=True, **PLAIN)
    s = display.summary
    native = _core.read_bytes(data, "{}").read_display(
        include_hidden=True, user_data_profile="disabled", image_profile="disabled"
    )
    assert s.to_dict() == json.loads(native.summary_json())
    assert s.status == "complete" and s.placement_status == "complete"
    assert s.placement_policy == "scene_graph_v1"
    assert s.configurations.selection == "none" and not s.configurations.candidates
    assert s.statistics.bodies == 1 and s.instance_count == 3 == s.statistics.instances
    assert s.document.hsf_version == "19.10"
    assert s.document.writer is None and s.document.mount_path is None
    [body] = s.bodies
    assert (body.vertex_count, body.triangle_count, body.edge_count) == (8, 12, 12)
    assert body.source_node_path == "/part" and body.instance_count == 3
    b = display.body_buffers(0)
    assert unpack(b.positions) == POINTS and b.normals is None
    mesh = scene.mesh_buffers(scene.summary.meshes[0].id)
    assert unpack(b.triangles) == unpack(mesh.triangles)
    edges = unpack(b.edges)
    assert len(edges) == 12 and all(a < c for a, c in edges)
    assert edges == tuple(sorted(edges))
    inst = display.instance_buffers()
    assert unpack(inst.matrices) == tuple(
        tuple(i.world_transform) for i in scene.summary.instances
    )
    assert unpack(inst.bodies) == (0, 0, 0)
    assert unpack(inst.colors) == ((255, 0, 0, 255), (0, 0, 255, 255), (255, 0, 0, 255))
    assert unpack(inst.color_sources) == (ed.COLOR_SOURCE_HSF,) * 3
    assert unpack(inst.face_visibility) == (2, 0, 0)
    assert unpack(inst.visibility) == (1, 0, 0)
    assert s.statistics.faces_off_instances == 2
    assert s.statistics.hidden_instances == 2
    assert [s.names[i] for i in unpack(inst.names)] == ["part", "place", "assembly"]
    assert s.component_paths == ("",)
    assert display.preview() is None
    codes = {d.code for d in s.diagnostics}
    assert "edrawings.display_colors" in codes
    assert "edrawings.display_placement_estimated" not in codes
    with pytest.raises(ed.InvalidFormatError, match="display.unknown_body"):
        display.body_buffers(1)


def test_materials_xml_default_colors_and_policies():
    body = opened("shared") + opened("body0") + opened("body0sub0") + shell() + b")))"
    xml = (
        b'<?xml version="1.0" encoding="UTF-8"?><Materials MaterialsVersion="1.0">'
        b'<Entity name="shared/body0"><Material><MaterialProps Transparency="0.5"/>'
        b'<RVAppearanceProps><MaterialColor1 red="10" green="20" blue="30"/>'
        b"</RVAppearanceProps></Material></Entity></Materials>"
    )
    data = make_zip([("eModel", HEADER + body + b"\0"), ("materials.xml", xml)])
    display = ed.read(data).read_display(**PLAIN)
    # The sub-body has no entity of its own; the parent body's material applies.
    assert unpack(display.instance_buffers().colors) == ((10, 20, 30, 128),)
    assert unpack(display.instance_buffers().color_sources) == (
        ed.COLOR_SOURCE_MATERIALS,
    )
    assert display.summary.document.materials_entry_id == "entry:1"
    assert display.summary.statistics.colors_from_materials == 1
    plain = ed.read(data).read_display(colors="hsf_only", **PLAIN)
    assert unpack(plain.instance_buffers().colors) == ((0, 0, 0, 0),)
    assert unpack(plain.instance_buffers().color_sources) == (ed.COLOR_SOURCE_NONE,)
    assert plain.summary.document.materials_entry_id is None
    # An inherited HSF colour wins over materials.xml.
    colored = make_zip(
        [
            (
                "eModel",
                HEADER + opened("shared") + b"~\x01\x01\x02\x03" + body + b")\0",
            ),
            ("materials.xml", xml),
        ]
    )
    display = ed.read(colored).read_display(**PLAIN)
    assert unpack(display.instance_buffers().colors) == ((1, 2, 3, 255),)
    assert unpack(display.instance_buffers().color_sources) == (ed.COLOR_SOURCE_HSF,)
    # A component's defaultcolor option is the last fallback.
    optioned = (
        HEADER
        + opened("assempart0")
        + option("defaultcolor=`0.5 0.25 1`, defaulttransmission=`0.75`")
        + opened("part")
        + shell()
        + b"))\0"
    )
    display = ed.read(optioned).read_display(**PLAIN)
    assert unpack(display.instance_buffers().colors) == ((128, 64, 255, 64),)
    assert unpack(display.instance_buffers().color_sources) == (ed.COLOR_SOURCE_OPTION,)
    # Unreadable materials are reported, not fatal.
    broken = make_zip(
        [("eModel", HEADER + body + b"\0"), ("materials.xml", b"<Materials>")]
    )
    # Metadata inspection at read time rejects the XML; display reports instead.
    display = ed.read(broken, read_metadata=False).read_display(**PLAIN)
    assert any(
        d.code == "edrawings.materials_unreadable" for d in display.summary.diagnostics
    )
    assert unpack(display.instance_buffers().color_sources) == (ed.COLOR_SOURCE_NONE,)


def test_configurations_show_one_saved_group():
    def config(segment, name, color):
        return (
            opened(segment)
            + option(f"config name=`{name}`")
            + opened("v")
            + color
            + shell()
            + b"))"
        )

    body = config("config1", "Beta", b"~\x01\0\0\xff") + config(
        "config0", "Alpha", b"~\x01\xff\0\0"
    )
    doc = ed.read(HEADER + body + b"\0")
    first = doc.read_display(**PLAIN)
    c = first.summary.configurations
    assert c.selection == "first"
    assert [x.segment_name for x in c.candidates] == ["config0", "config1"]
    assert [x.name for x in c.candidates] == ["Alpha", "Beta"]
    # Only the selected configuration is traversed; the other candidate places nothing.
    assert [x.instances for x in c.candidates] == [1, 0]
    assert c.selected_node_id == c.candidates[0].node_id
    assert first.summary.instance_count == 1
    assert first.summary.statistics.instances_before_configuration_filter == 1
    assert "hsf.traversal_subtree" in {d.code for d in first.summary.diagnostics}
    assert first.summary.statistics.bodies == 2
    assert first.summary.statistics.unplaced_bodies == 1
    assert unpack(first.instance_buffers().colors) == ((255, 0, 0, 255),)
    codes = {d.code for d in first.summary.diagnostics}
    assert {
        "edrawings.display_configuration_selected",
        "edrawings.display_unplaced_bodies",
    } <= codes
    beta = doc.read_display(configuration="Beta", **PLAIN)
    assert beta.summary.configurations.selection == "explicit"
    assert unpack(beta.instance_buffers().colors) == ((0, 0, 255, 255),)
    assert (
        doc.read_display(configuration="config1", **PLAIN).summary.instance_count == 1
    )
    with pytest.raises(ed.InvalidFormatError, match="display.configuration_unknown"):
        doc.read_display(configuration="Gamma", **PLAIN)


def test_first_header_mount_path_and_candidate_drive_the_bundle():
    ancestors = ["sheet0", "view0", "3dmodel", "includes", "instance0"]
    body = (
        opened("config0")
        + option("config name=`config`")
        + b"".join(opened(n) for n in ancestors)
        # Opened from six levels down against a mount two levels deep: the library
        # lands at /shared inside this file, then the component includes it.
        + opened(CLIMB.decode())
        + opened("body0")
        + shell()
        + b"))"
        + include(CLIMB)
        + b")" * 6
        + opened("config1")
        + option("config name=`other`")
        + b")"
    )
    data = packed(
        sample(51, 1, include_path=MOUNT) + b"h\0" + body + b"\1" + terminal(51) + b"z"
    )
    doc = ed.read(data)
    verified = doc.read_scene(user_data_profile="edrawings_be_envelope_v1")
    assert verified.summary.placement_status == "unsupported"
    assert not verified.summary.instances
    assert not any(d.code == "hsf.segment_path" for d in verified.summary.diagnostics)
    estimated = doc.read_scene(
        user_data_profile="edrawings_be_envelope_v1", placement="scene_graph_v1"
    )
    assert estimated.summary.placement_status == "partial"
    assert len(estimated.summary.instances) == 1
    assert any(
        d.code == "hsf.placement_estimated" for d in estimated.summary.diagnostics
    )
    # Strict mode never accepts estimated placements (checked before any record;
    # here on a plain stream, since strict already rejects experimental User Data).
    with pytest.raises(
        ed.UnsupportedFeatureError, match="hsf.placement_policy_rejected"
    ):
        ed.read(HEADER + assembly() + b"\0").read_scene(
            mode="strict", placement="scene_graph_v1"
        )
    display = doc.read_display()
    s = display.summary
    assert s.document.mount_path == MOUNT.decode()
    assert s.document.configuration_candidate == "config"
    assert s.document.revision_history == "51;"
    assert s.document.user_data_profile is not None
    assert s.document.user_data_profile.endswith("revision-51")
    # The header string is reported but never selects: no hidden marker -> first.
    assert s.configurations.selection == "first"
    assert s.configurations.active_node_id is None
    assert [x.name for x in s.configurations.candidates] == ["config", "other"]
    assert [x.hidden for x in s.configurations.candidates] == [False, False]
    assert s.instance_count == 1 and s.statistics.bodies == 1
    assert s.statistics.unplaced_bodies == 0
    assert s.bodies[0].source_node_path == "/shared/body0"
    assert s.placement_status == "partial"
    assert any(d.code == "edrawings.display_placement_estimated" for d in s.diagnostics)
    assert [s.names[i] for i in unpack(display.instance_buffers().names)] == [
        "instance0"
    ]
    assert display.summary.to_dict()["statistics"]["instances"] == 1


def test_revision_histories_writer_and_year_hint():
    good = packed(header(51, b"47;51;") + b"h\0\1" + terminal(51) + b"z")
    doc = ed.read(good)
    parsed = doc.parse_hsf(user_data_profile="edrawings_be_envelope_v1")
    assert len(parsed.summary.records) > 3
    assert parsed.summary.records[3].user_data is not None
    assert not any(
        d.code == "edrawings.user_data_profile_mismatch"
        for d in parsed.summary.diagnostics
    )
    s = doc.read_display().summary
    assert s.document.writer == "SWeModels-26.0.1.0001-2017284"
    assert s.document.writer_year_hint == 2018
    assert s.document.revision_history == "47;51;"
    assert s.document.configuration_candidate == "Config-12"
    bad = packed(header(51, b"51;47;") + b"h\0\1" + terminal(51) + b"z")
    parsed = ed.read(bad).parse_hsf(user_data_profile="edrawings_be_envelope_v1")
    assert len(parsed.summary.records) == 3
    assert any(
        d.code == "edrawings.user_data_profile_mismatch"
        for d in parsed.summary.diagnostics
    )


def test_cli_display_and_preview(tmp_path):
    path = tmp_path / "part.eprt"
    path.write_bytes(
        make_zip(
            [
                ("eModel", HEADER + assembly() + b"\0"),
                ("preview.jpg", b"\xff\xd8\xff\xd9"),
            ]
        )
    )
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "edrawings_kit",
            "display",
            str(path),
            "--user-data-profile",
            "disabled",
            "--image-profile",
            "disabled",
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    out = json.loads(run.stdout)
    assert out["instance_count"] == 1
    assert out["statistics"]["hidden_instances"] == 2
    assert out["document"]["preview_entry_id"] == "entry:1"
    assert out["document"]["preview_media_type"] == "image/jpeg"
    display = ed.read_file(path).read_display(**PLAIN)
    assert display.preview() == (b"\xff\xd8\xff\xd9", "image/jpeg")
    assert ed.Limits.service().max_hsf_records == 2_000_000


def test_hidden_configuration_marker_selects_the_active_one():
    # eDrawings hides every configuration except the current one with a face
    # visibility off record on its segment; config0 hidden -> config1 is active.
    def config(segment, name, marker, color):
        return (
            opened(segment)
            + option(f"config name=`{name}`")
            + marker
            + opened("v")
            + color
            + shell()
            + b"))"
        )

    body = config("config0", "Alpha", b"V\x01\x00", b"~\x01\xff\0\0") + config(
        "config1", "Beta", b"", b"~\x01\0\0\xff"
    )
    doc = ed.read(HEADER + body + b"\0")
    display = doc.read_display(**PLAIN)
    c = display.summary.configurations
    assert c.selection == "active"
    assert [x.hidden for x in c.candidates] == [True, False]
    assert c.active_node_id == c.candidates[1].node_id == c.selected_node_id
    assert [x.instances for x in c.candidates] == [0, 1]
    assert unpack(display.instance_buffers().colors) == ((0, 0, 255, 255),)
    # An explicit request still wins over the active marker.
    alpha = doc.read_display(configuration="Alpha", **PLAIN)
    assert alpha.summary.configurations.selection == "explicit"
    assert unpack(alpha.instance_buffers().colors) == ((255, 0, 0, 255),)


def test_display_state_and_default_visibility_decide_what_is_shown():
    # hid: HSF face visibility off, re-shown by the display state; shown: default
    # on but hidden by the display state; plain: off with no override.
    body = (
        opened("config0")
        + option("config name=`A`")
        + opened("displaystates")
        + option("default=disp0,current=`disp0`")
        + opened("disp0")
        + opened("comp0")
        + option("path=config0/v/hid,vis=on")
        + b")"
        + opened("comp1")
        + option("path=config0/v/shown,vis=off")
        + b")"
        + b"))"
        + opened("v")
        + opened("hid")
        + b"V\x01\x00~\x01\xff\0\0"
        + shell()
        + b")"
        + opened("shown")
        + b"~\x01\0\xff\0"
        + shell()
        + b")"
        + opened("plain")
        + b"V\x01\x00~\x01\0\0\xff"
        + shell()
        + b")"
        + opened("marked")
        + option("defaultvisibility=off")
        + b"~\x01\x80\x80\x80"
        + shell()
        + b")"
        + b"))"
    )
    doc = ed.read(HEADER + body + b"\0")
    display = doc.read_display(**PLAIN)
    s = display.summary
    assert s.configurations.candidates[0].display_state == "disp0"
    assert s.instance_count == 1
    assert s.statistics.hidden_instances == 3
    assert s.statistics.faces_off_instances == 2
    assert s.statistics.hidden_bodies == 3
    assert s.statistics.unplaced_bodies == 0
    assert unpack(display.instance_buffers().colors) == ((255, 0, 0, 255),)
    assert unpack(display.instance_buffers().visibility) == (1,)
    assert unpack(display.instance_buffers().face_visibility) == (0,)
    codes = {d.code: d.message for d in s.diagnostics}
    assert "display state disp0" in codes["edrawings.display_hidden_components"]
    everything = doc.read_display(include_hidden=True, **PLAIN)
    assert everything.summary.instance_count == 4
    assert everything.summary.statistics.hidden_instances == 3
    assert unpack(everything.instance_buffers().visibility) == (1, 0, 0, 0)
    assert unpack(everything.instance_buffers().face_visibility) == (0, 2, 0, 2)


def test_other_display_states_can_be_applied_by_segment_or_name():
    body = (
        opened("config0")
        + option("config name=`A`")
        + opened("displaystates")
        + option("default=disp0,current=`disp0`")
        + opened("disp0")
        + option("name=`Display State-1`")
        + opened("comp0")
        + option("path=config0/v/a,vis=off")
        + b")"
        + b")"
        + opened("disp1")
        + option("name=`Open`")
        + opened("comp0")
        + option("path=config0/v/b,vis=off")
        + b")"
        + opened("comp1")
        + option("path=config0/v/c,vis=on")
        + b")"
        + b")"
        + b")"
        + opened("v")
        + opened("a")
        + b"~\x01\xff\0\0"
        + shell()
        + b")"
        + opened("b")
        + b"~\x01\0\xff\0"
        + shell()
        + b")"
        + opened("c")
        + b"V\x01\x00~\x01\0\0\xff"
        + shell()
        + b")"
        + b"))"
    )
    doc = ed.read(HEADER + body + b"\0")
    current = doc.read_display(**PLAIN)
    c = current.summary.configurations
    assert c.shown_display_state == "disp0"
    assert c.display_state_selection == "current"
    states = c.candidates[0].display_states
    assert [
        (s.segment_name, s.name, s.current, s.default, s.components) for s in states
    ] == [
        ("disp0", "Display State-1", True, True, 1),
        ("disp1", "Open", False, False, 2),
    ]
    # disp0 hides a; c is hidden by its own flag.
    assert unpack(current.instance_buffers().colors) == ((0, 255, 0, 255),)
    for wanted in ("disp1", "Open"):
        other = doc.read_display(display_state=wanted, **PLAIN)
        assert other.summary.configurations.shown_display_state == "disp1"
        assert other.summary.configurations.display_state_selection == "explicit"
        # disp1 hides b and re-shows c.
        assert unpack(other.instance_buffers().colors) == (
            (255, 0, 0, 255),
            (0, 0, 255, 255),
        )
    with pytest.raises(ed.InvalidFormatError, match="display.display_state_unknown"):
        doc.read_display(display_state="Closed", **PLAIN)
