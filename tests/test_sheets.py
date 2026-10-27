"""Stored sheet/view ownership and provenance, without inferred projection."""

import dataclasses
import gc
import json
import struct
import subprocess
import sys
from pathlib import Path

import edrawings_kit as ed
import pytest
from edrawings_kit import _core
from test_components import opened
from test_document_options import options
from test_scene import shell
from test_terminal_user_data import make

PROFILE = "edrawings_be_envelope_v1"
LINE = b"l" + struct.pack("<6f", 0, 0, 0, 100, 0, 0)


def group(segment, body):
    return opened(segment) + body + b")"


def named(segment, label, body, *, extra=b""):
    return group(segment, options(f"name=`{label}`", "utf-16-le") + extra + body)


def view(segment="view0", label="Drawing View 1", body=LINE, *, extra=b""):
    return named(segment, label, group("2dmodel", body), extra=extra)


def sheet(segment="sheet0", label="Model", body=None, *, extra=b""):
    return named(segment, label, view() if body is None else body, extra=extra)


def wire(body):
    return make(revision=51, middle=b"h\0" + body + b"\1")


def read(body):
    return ed.read(wire(body)).read_drawing(user_data_profile=PROFILE)


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed"])
def test_inventory_source_order_unicode_geometry_and_no_reference_expansion(
    wrapper, zip_factory
):
    # Unrelated root/library geometry is not moved into a sheet. The include
    # points at a real definition, but must not duplicate it in view ownership.
    reference = b"<" + bytes([len("/library/item")]) + b"/library/item"
    body = LINE + group("library", group("item", LINE + shell()))
    body += sheet(
        "sheet2",
        "図面,A=B 🦀",
        LINE
        + view(body=group("layer", LINE + shell()) + reference)
        + view("borderview0", "Border", LINE),
    )
    body += sheet("sheet0", "図面,A=B 🦀", view(label="Drawing View 1"))
    data = wire(body)
    if wrapper != "raw":
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    drawing = doc.read_drawing(user_data_profile=PROFILE)
    inv = drawing.summary.sheet_inventory
    assert isinstance(inv, ed.SheetInventory)
    assert inv.profile == "edrawings_root_sheet_view_v1"
    assert inv.status == "complete" and inv.reason is None
    a, b = inv.sheets
    v, border, other = inv.views
    assert all(isinstance(item, ed.StoredSheet) for item in inv.sheets)
    assert [s.segment_name for s in inv.sheets] == ["sheet2", "sheet0"]
    assert a.name.value == b.name.value == "図面,A=B 🦀"
    # Repeated labels are not identifiers, nor are numeric suffixes API indices.
    assert a.node_id != b.node_id and v.node_id != other.node_id
    assert a.view_node_ids == (v.node_id, border.node_id)
    assert b.view_node_ids == (other.node_id,)
    assert v.kind == other.kind == "view" and border.kind == "border_view"
    assert v.sheet_node_id == border.sheet_node_id == a.node_id
    assert len(a.primitive_ids) == 3 and len(a.mesh_ids) == 1
    assert len(v.primitive_ids) == len(v.mesh_ids) == 1
    assert len(b.primitive_ids) == 1 and not b.mesh_ids
    assert len(drawing.summary.scene.primitives) == 6
    assert len(drawing.summary.scene.meshes) == 2
    assert v.model_2d_node_id is not None and v.model_3d_node_id is None
    assert drawing.summary.to_dict() == json.loads(
        _core.read_bytes(data, "{}")
        .read_drawing(user_data_profile=PROFILE)
        .summary_json()
    )
    for item in (*inv.sheets, *inv.views):
        assert isinstance(item.name, ed.StoredDrawingName)
        assert (
            drawing.source_bytes(item.segment_name_source) == item.segment_name.encode()
        )
        assert drawing.source_bytes(item.name.source) == item.name.value.encode(
            "utf-16-le"
        )
        assert item.name.encoding == "utf_16_le"
        assert item.name.source_record_id in {
            r.source_record_id for r in drawing.summary.user_option_records
        }
    assert drawing.summary.assessment.sheet_status == "unsupported"
    assert drawing.summary.assessment.view_status == "unsupported"
    assert drawing.summary.scene.units is None
    assert not drawing.summary.scene.primitive_instances
    assert not drawing.summary.scene.instances
    assert not {"scale", "native_index", "paper_size", "camera"} & a.to_dict().keys()
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.name.value = "other"
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.read_drawing(mode="strict", user_data_profile=PROFILE)
    del doc
    gc.collect()
    assert drawing.source_bytes(a.name.source) == a.name.value.encode("utf-16-le")


@pytest.mark.parametrize(
    "extra",
    [options("name=Other"), options("NAME=Model"), options("name=Model,name=Other")],
)
@pytest.mark.parametrize("location", ["sheet", "view"])
def test_duplicate_name_assignments_never_choose_first_or_last(extra, location):
    body = sheet(extra=extra) if location == "sheet" else sheet(body=view(extra=extra))
    inv = read(body).summary.sheet_inventory
    assert inv.reason == "drawing.sheet_name_ambiguous"
    assert not inv.sheets and not inv.views


@pytest.mark.parametrize(
    "name_record",
    [b"", options("name"), options("name=''"), options("name=ok,b=`unfinished")],
)
@pytest.mark.parametrize("location", ["sheet", "view"])
def test_missing_implicit_empty_and_partial_names_are_unavailable(
    name_record, location
):
    body = (
        group("sheet0", name_record + view())
        if location == "sheet"
        else sheet(body=group("view0", name_record + group("2dmodel", LINE)))
    )
    inv = read(body).summary.sheet_inventory
    assert inv.reason == "drawing.sheet_name_unavailable"
    assert not inv.sheets and not inv.views


@pytest.mark.parametrize(
    "body",
    [
        group("config0", sheet()),
        group("unknown", sheet()),
        sheet() + group("config0", b""),
        sheet(body=group("unknown", view())),
        sheet(body=group("view_extra", group("2dmodel", LINE))),
        sheet(body=named("view0", "View", b"")),
        sheet(body=b""),
        sheet() + group("sheet00", view()),
        sheet(body=view(body=sheet("sheet1", "Nested"))),
    ],
)
def test_unrecognized_structure_does_not_expose_a_partial_inventory(body):
    inv = read(body).summary.sheet_inventory
    assert inv.status == "unsupported"
    assert inv.reason == "drawing.sheet_structure_unverified"
    assert not inv.sheets and not inv.views


def test_missing_profile_incomplete_scene_and_no_sheet_are_distinguished():
    data = wire(sheet())
    assert ed.read(data).read_drawing().summary.sheet_inventory.reason == (
        "drawing.sheet_profile_unavailable"
    )
    assert read(sheet() + b"\xfe").summary.sheet_inventory.reason == (
        "drawing.sheet_inventory_incomplete"
    )
    assert read(LINE).summary.sheet_inventory.reason == "drawing.sheet_structure_absent"
    old = make(revision=39, version="14.50", middle=b"h\0" + sheet() + b"\1")
    assert ed.read(old).read_drawing(
        user_data_profile=PROFILE
    ).summary.sheet_inventory.reason == ("drawing.sheet_profile_unavailable")


def test_reopened_geometry_retains_definition_owner_and_3d_model_root():
    body = sheet(body=named("view0", "View", group("3dmodel", LINE) + b"q"))
    # The model node is tag zero; a reopened definition belongs to the same view.
    body += b"s\0\0\0\0" + LINE + b")"
    d = read(body)
    (v,) = d.summary.sheet_inventory.views
    assert v.model_2d_node_id is None and v.model_3d_node_id is not None
    assert v.primitive_ids == tuple(p.id for p in d.summary.scene.primitives)
    assert len(v.primitive_ids) == 2


def test_805_revision22_sheet_convention_observed_in_native_525():
    body = group(
        "sheet0",
        options("name=Model")
        + group("view0", options("name=Drawing View 1") + group("2dmodel", LINE)),
    )
    data = make(revision=22, version="8.05", middle=b"h\0" + body + b"\1")
    d = ed.read(data).read_drawing(user_data_profile=PROFILE)
    inv = d.summary.sheet_inventory
    assert inv.status == "complete"
    assert inv.sheets[0].name.value == "Model"
    assert drawing_bytes(d, inv.views[0].name) == "Drawing View 1"
    assert inv.views[0].primitive_ids == (d.summary.scene.primitives[0].id,)


def test_inventory_output_shares_exact_total_budget():
    data = wire(sheet(label="x" * 5000))
    d = ed.read(data).read_drawing(user_data_profile=PROFILE)
    used = d.summary.scene.usage.output_bytes
    same = ed.read(data, limits=ed.Limits(max_output_bytes=used)).read_drawing(
        user_data_profile=PROFILE
    )
    assert same.summary == d.summary
    with pytest.raises(ed.LimitExceededError):
        ed.read(data, limits=ed.Limits(max_output_bytes=used - 1)).read_drawing(
            user_data_profile=PROFILE
        )


@pytest.mark.parametrize("kind", ["sheet", "view"])
def test_inventory_count_limits_are_bounded(kind):
    many = b"".join(group(f"{kind}{i}", b"") for i in range(10_001))
    body = many if kind == "sheet" else group("sheet0", many)
    with pytest.raises(ed.LimitExceededError, match=f"limits.document_{kind}s"):
        read(body)


@pytest.mark.parametrize(
    "filename",
    [
        "two-layouts-mm.edrw",
        "two-layouts-visible-mm.edrw",
    ],
)
def test_native_fixtures_names_and_complete_geometry_partition(filename):
    path = Path(__file__).parent / "fixtures/native-m4" / filename
    d = ed.read_file(path).read_drawing(
        user_data_profile=PROFILE, image_profile="edrawings_1910_u32_v1"
    )
    inv = d.summary.sheet_inventory
    assert inv.status == "complete"
    assert [s.name.value for s in inv.sheets] == ["M4_SHEET_B", "M4_SHEET_A", "Model"]
    assert [s.segment_name for s in inv.sheets] == ["sheet2", "sheet1", "sheet0"]
    assert [len(s.view_node_ids) for s in inv.sheets] == [2, 2, 1]
    # Independently derive ownership from parent links, not the implementation's
    # inventory. Global HSF NamedView is not a sheet view.
    nodes = {n.id: n for n in d.summary.scene.nodes}
    for item in (*inv.sheets, *inv.views):
        expected = []
        for p in d.summary.scene.primitives:
            owner = p.owner_node_id
            while owner is not None:
                if owner == item.node_id:
                    expected.append(p.id)
                    break
                owner = nodes[owner].parent_id
        assert item.primitive_ids == tuple(expected)
        assert drawing_bytes(d, item.name) == item.name.value
    assert sum(len(s.primitive_ids) for s in inv.sheets) == len(
        d.summary.scene.primitives
    )
    assert sum(len(v.primitive_ids) for v in inv.views) == len(
        d.summary.scene.primitives
    )
    assert not any(s.mesh_ids for s in inv.sheets)
    assert len(inv.views) == 5
    assert {v.node_id for v in inv.views}.isdisjoint(
        v.context_node_id for v in d.summary.scene.views
    )
    assert (
        d.summary.assessment.sheet_status
        == d.summary.assessment.view_status
        == "unsupported"
    )


def drawing_bytes(drawing, label):
    encodings = {"ascii": "ascii", "iso_8859_1": "latin1", "utf_16_le": "utf-16-le"}
    return drawing.source_bytes(label.source).decode(encodings[label.encoding])


def test_cli_exposes_same_inventory_and_distinct_status(tmp_path):
    path = tmp_path / "sheets.hsf"
    path.write_bytes(wire(sheet()))
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "edrawings_kit",
            "drawing",
            str(path),
            "--user-data-profile",
            PROFILE,
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    data = json.loads(result.stdout)
    assert (
        data
        == ed.read_file(path, read_metadata=False)
        .read_drawing(user_data_profile=PROFILE)
        .summary.to_dict()
    )
    assert data["sheet_inventory"]["status"] == "complete"
    assert data["assessment"]["sheet_status"] == "unsupported"
