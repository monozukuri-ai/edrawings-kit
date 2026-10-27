"""Stored multi-configuration names/ownership, independent of active selection."""

import dataclasses
import json
import struct
import subprocess
import sys

import edrawings_kit as ed
import pytest
from test_components import component, opened
from test_terminal_user_data import make


def option(value):
    value = value.encode("ascii")
    return b"U" + struct.pack("<H", len(value)) + value


def config(segment, name, body=None, extra=b""):
    if body is None:
        body = component("assempart0", "leaf")
    ancestors = ["sheet0", "view0", "3dmodel", "includes"]
    return (
        opened(segment)
        + option(f"config name=`{name}`")
        + extra
        + b"".join(opened(n) for n in ancestors)
        + body
        + b")" * 5
    )


def read(body, **kwargs):
    return ed.read(make(middle=b"h\0" + body + b"\1")).read_drawing(
        user_data_profile="edrawings_be_envelope_v1", **kwargs
    )


def test_multiple_config_sources_and_component_membership_cli(tmp_path):
    body = config("config1", "Second") + config(
        "config0",
        "First",
        component("subassem0", "assembly", children=component("assempart0", "leaf")),
    )
    drawing = read(body)
    inv = drawing.summary.configuration_inventory
    assert isinstance(inv, ed.ConfigurationInventory) and inv.status == "complete"
    assert inv.active_configuration_node_id is None
    assert [c.segment_name for c in inv.configurations] == ["config1", "config0"]
    assert [c.name.value for c in inv.configurations] == ["Second", "First"]
    assert [len(c.component_node_ids) for c in inv.configurations] == [1, 2]
    for c in inv.configurations:
        assert isinstance(c, ed.StoredConfiguration)
        assert drawing.source_bytes(c.name.source).decode() == c.name.value
        assert drawing.source_bytes(c.segment_name_source).decode() == c.segment_name
        assert set(c.component_node_ids).issubset(
            {n.id for n in drawing.summary.scene.nodes}
        )
    assert drawing.summary.assessment.configuration_status == "unsupported"
    with pytest.raises(dataclasses.FrozenInstanceError):
        inv.active_configuration_node_id = "guess"
    data = make(middle=b"h\0" + body + b"\1")
    path = tmp_path / "configs.hsf"
    path.write_bytes(data)
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "edrawings_kit",
            "drawing",
            str(path),
            "--user-data-profile",
            "edrawings_be_envelope_v1",
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    assert json.loads(proc.stdout)["configuration_inventory"] == inv.to_dict()


def test_explicit_import_context_retained_without_active_or_world_claim():
    d = read(
        config("config0", "A") + config("config1", "B"),
        import_root="/include library/model_1_include",
    )
    assert d.summary.configuration_inventory.status == "complete"
    assert d.summary.configuration_inventory.active_configuration_node_id is None
    assert d.summary.scene.import_context.interpretation_status == "unsupported"
    assert d.summary.scene.placement_status == "unsupported"


@pytest.mark.parametrize(
    "body,reason",
    [
        (config("config0", "Default"), "drawing.multiple_configurations_absent"),
        (
            config("config0", "A") + config("config1", "A"),
            "drawing.configuration_name_ambiguous",
        ),
        (
            config("config0", "A") + config("config2", "B"),
            "drawing.configuration_name_ambiguous",
        ),
        (
            config("config0", "A", extra=option("config name=Other"))
            + config("config1", "B"),
            "drawing.configuration_name_ambiguous",
        ),
        (
            config("config0", "") + config("config1", "B"),
            "drawing.configuration_name_unavailable",
        ),
        (
            opened("wrong") + config("config0", "A") + b")" + config("config1", "B"),
            "drawing.configuration_structure_unverified",
        ),
        (
            opened("config0")
            + option("config name=A")
            + component("assempart0", "bad")
            + b")"
            + config("config1", "B"),
            "drawing.configuration_component_context_unverified",
        ),
    ],
)
def test_ambiguous_or_unmatched_configuration_shapes_fail_closed(body, reason):
    inv = read(body).summary.configuration_inventory
    assert (
        inv.status == "unsupported" and inv.reason == reason and not inv.configurations
    )


def test_incomplete_source_and_limits_remain_explicit():
    body = config("config0", "A") + config("config1", "B")
    assert (
        read(body + b"\xfe").summary.configuration_inventory.reason
        == "drawing.configuration_inventory_incomplete"
    )
    data = make(middle=b"h\0" + body + b"\1")
    d = ed.read(data).read_drawing(user_data_profile="edrawings_be_envelope_v1")
    used = d.summary.scene.usage.output_bytes
    assert (
        ed.read(data, limits=ed.Limits(max_output_bytes=used))
        .read_drawing(user_data_profile="edrawings_be_envelope_v1")
        .summary
        == d.summary
    )
    with pytest.raises(ed.LimitExceededError):
        ed.read(data, limits=ed.Limits(max_output_bytes=used - 1)).read_drawing(
            user_data_profile="edrawings_be_envelope_v1"
        )
