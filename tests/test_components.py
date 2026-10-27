"""Saved component metadata, separate from Reader-generated roots/config lists."""

import dataclasses
import json
import struct

import edrawings_kit as ed
import pytest
from edrawings_kit import _core
from test_terminal_user_data import make


def opened(name):
    data = name.encode("ascii")
    return b"(" + bytes([len(data)]) + data


def text(value):
    data = value.encode("utf-16-le")
    return b"x" + bytes(12) + b"\x05\xff" + struct.pack("<I", len(data)) + data + b"\0"


def field(name, value):
    return opened(name) + text(value) + b")"


def component(
    segment, name, *, children=b"", reference_name=None, path="model.sldprt", extra=b""
):
    return (
        opened(segment)
        + field("name", name)
        + opened("reference")
        + field("refname", name if reference_name is None else reference_name)
        + field("path", path)
        + b")"
        + children
        + extra
        + b")"
    )


def wire(body, *, root="includes", version="19.10"):
    ancestors = ["config0", "sheet0", "view0", "3dmodel", root]
    return make(
        version=version,
        middle=b"h\0"
        + b"".join(opened(n) for n in ancestors)
        + body
        + b")" * len(ancestors)
        + b"\1",
    )


def read(body, **kwargs):
    return ed.read(wire(body, **kwargs)).read_drawing(
        user_data_profile="edrawings_be_envelope_v1"
    )


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed"])
def test_saved_tree_sources_unicode_references_and_no_filename_prefix(
    wrapper, zip_factory
):
    body = component(
        "subassem0",
        "部品組立 🦀",
        children=component(
            "assempart1",
            "Part / syntax".replace(" / ", "-"),
            reference_name="OriginalPart",
            path=r"C:\design\part.sldprt",
        ),
    )
    data = wire(body)
    if wrapper != "raw":
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    drawing = ed.read(data).read_drawing(user_data_profile="edrawings_be_envelope_v1")
    inv = drawing.summary.component_inventory
    assert isinstance(inv, ed.ComponentInventory)
    assert inv.status == "complete" and inv.reason is None
    a, b = inv.components
    assert isinstance(a, ed.StoredComponent) and isinstance(a.name, ed.ComponentText)
    assert [a.relative_path, b.relative_path] == [
        "部品組立 🦀",
        "部品組立 🦀/Part-syntax",
    ]
    assert a.parent_component_node_id is None
    assert b.parent_component_node_id == a.node_id
    assert a.root_node_id == b.root_node_id
    assert b.reference_name.text.value == "OriginalPart"
    assert b.reference_path.text.value == r"C:\design\part.sldprt"
    primitives = {p.id: p for p in drawing.summary.scene.primitives}
    for item in (a, b):
        for value in (item.name, item.reference_name, item.reference_path):
            assert primitives[value.primitive_id].text == value.text
            assert drawing.source_bytes(value.text.source) == value.text.value.encode(
                "utf-16-le"
            )
    assert drawing.summary.assessment.configuration_status == "unsupported"
    assert drawing.summary.scene.placement_status == "unsupported"
    assert drawing.summary.to_dict() == json.loads(
        _core.read_bytes(data, "{}")
        .read_drawing(user_data_profile="edrawings_be_envelope_v1")
        .summary_json()
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.relative_path = "changed"


@pytest.mark.parametrize("bad_name", ["", "a/b", "a\0b"])
def test_ambiguous_names_are_not_escaped_or_invented(bad_name):
    inv = read(component("assempart0", bad_name)).summary.component_inventory
    assert inv.status == "unsupported" and not inv.components
    assert inv.reason == "drawing.component_name_ambiguous"


@pytest.mark.parametrize(
    "extra",
    [field("name", "second"), opened("reference") + field("path", "other") + b")"],
)
def test_duplicate_metadata_is_not_last_wins(extra):
    inv = read(component("assempart0", "a", extra=extra)).summary.component_inventory
    assert inv.reason == "drawing.component_field_ambiguous" and not inv.components


def test_duplicate_sibling_names_are_ambiguous_but_distinct_roots_are_separate():
    inv = read(
        component("assempart0", "a") + component("assempart1", "a")
    ).summary.component_inventory
    assert inv.reason == "drawing.component_path_ambiguous" and not inv.components
    body = component("subassem0", "A", children=component("assempart0", "same"))
    body += component("subassem1", "B", children=component("assempart0", "same"))
    inv = read(body).summary.component_inventory
    assert inv.status == "complete"
    assert {c.relative_path for c in inv.components} == {"A", "A/same", "B", "B/same"}


def test_missing_fields_wrong_context_incomplete_scene_and_no_profile_fail_closed():
    inv = read(
        opened("assempart0") + field("name", "a") + b")"
    ).summary.component_inventory
    assert inv.reason == "drawing.component_fields_missing"
    inv = read(component("assempart0", "a"), root="other").summary.component_inventory
    assert inv.reason == "drawing.component_root_unverified"
    data = wire(component("assempart0", "a") + b"\xfe")
    inv = (
        ed.read(data)
        .read_drawing(user_data_profile="edrawings_be_envelope_v1")
        .summary.component_inventory
    )
    assert inv.reason == "drawing.component_inventory_incomplete"
    inv = (
        ed.read(wire(component("assempart0", "a")))
        .read_drawing()
        .summary.component_inventory
    )
    assert inv.reason == "drawing.component_profile_unavailable"


def test_geometry_in_metadata_leaf_is_not_silently_discarded():
    inv = read(
        component("assempart0", "a", extra=opened("name") + b"l" + bytes(24) + b")")
    ).summary.component_inventory
    assert inv.reason == "drawing.component_text_unavailable" and not inv.components


def test_output_budget_is_shared_with_scene_and_options():
    data = wire(component("assempart0", "x" * 5000))
    doc = ed.read(data)
    s = doc.read_scene(user_data_profile="edrawings_be_envelope_v1").summary
    limited = ed.read(
        data, limits=ed.Limits(max_output_bytes=s.usage.output_bytes + 1024)
    )
    with pytest.raises(ed.LimitExceededError):
        limited.read_drawing(user_data_profile="edrawings_be_envelope_v1")


def part_matrix(x=12.5):
    return b"%" + struct.pack("<12f", 0, 1, 0, -1, 0, 0, 0, 0, 1, x, -2, 3)


def test_direct_part_transform_sources_cli_and_no_assembly_identity(tmp_path):
    import subprocess
    import sys

    matrix_bytes = part_matrix()
    body = component(
        "subassem0",
        "assembly",
        children=component(
            "assempart0", "leaf", extra=opened("part") + matrix_bytes + b")"
        ),
    )
    data = wire(body)
    drawing = ed.read(data).read_drawing(user_data_profile="edrawings_be_envelope_v1")
    assembly, leaf = drawing.summary.component_inventory.components
    assert assembly.part_transform is None
    part = leaf.part_transform
    assert isinstance(part, ed.StoredPartTransform)
    assert part.matrix.value == (0, 1, 0, 0, -1, 0, 0, 0, 0, 0, 1, 0, 12.5, -2, 3, 1)
    node = next(n for n in drawing.summary.scene.nodes if n.id == part.part_node_id)
    assert node.parent_id == leaf.node_id and node.name == "part"
    assert node.local_transform == part.matrix
    assert drawing.source_bytes(part.matrix.source) == matrix_bytes
    assert drawing.summary.assessment.component_status == "unsupported"
    assert drawing.summary.scene.placement_status == "unsupported"

    # Every nested source survives the public typed/JSON contract and resolves.
    def spans(value):
        if isinstance(value, ed.HsfSpan):
            yield value
        elif dataclasses.is_dataclass(value):
            for f in dataclasses.fields(value):
                yield from spans(getattr(value, f.name))
        elif isinstance(value, (tuple, list)):
            for item in value:
                yield from spans(item)

    assert list(spans(part)) == [part.matrix.source]
    for source in spans(drawing.summary.component_inventory):
        assert len(drawing.source_bytes(source)) == source.length
    path = tmp_path / "component.hsf"
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
    assert (
        json.loads(proc.stdout)["component_inventory"]
        == drawing.summary.component_inventory.to_dict()
    )
    assert drawing.summary.to_dict() == json.loads(
        _core.read_bytes(data, "{}")
        .read_drawing(user_data_profile="edrawings_be_envelope_v1")
        .summary_json()
    )


@pytest.mark.parametrize(
    "extra,reason",
    [
        (
            opened("part") + part_matrix() + part_matrix(20) + b")",
            "drawing.component_part_matrix_ambiguous",
        ),
        (
            opened("part") + part_matrix() + b")" + opened("part") + b")",
            "drawing.component_part_ambiguous",
        ),
        (
            opened("part") + b")" + opened("part") + part_matrix() + b")",
            "drawing.component_part_ambiguous",
        ),
    ],
)
def test_reopened_parts_and_multiple_matrices_are_not_last_wins(extra, reason):
    inventory = read(
        component("assempart0", "leaf", extra=extra)
    ).summary.component_inventory
    assert inventory.status == "unsupported" and inventory.reason == reason
    assert not inventory.components


def test_missing_and_nested_part_matrices_are_not_guessed():
    for extra in [
        opened("part") + b")",
        opened("other") + opened("part") + part_matrix() + b"))",
    ]:
        inv = read(
            component("assempart0", "leaf", extra=extra)
        ).summary.component_inventory
        assert inv.status == "complete" and inv.components[0].part_transform is None
    with pytest.raises(ed.InvalidFormatError, match="hsf.invalid_transform"):
        read(
            component(
                "assempart0",
                "leaf",
                extra=opened("part") + part_matrix(float("nan")) + b")",
            )
        )
