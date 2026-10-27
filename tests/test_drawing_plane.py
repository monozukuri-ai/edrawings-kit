"""Native-verified writer-plane unit hints, separate from XYZ/model dimensions."""

import dataclasses
import json
import struct
import subprocess
import sys
from pathlib import Path

import edrawings_kit as ed
import pytest
from edrawings_kit import _core
from test_document_options import options
from test_sheets import LINE, group, sheet, view
from test_terminal_user_data import packed, terminal
from test_user_data_audit import blob

PROFILE = "edrawings_be_envelope_v1"
WRITER = b"DXF/DWG Reader AddIn (34.4.1.0003)"
IDENTITY = tuple(1.0 if i % 5 == 0 else 0.0 for i in range(16))


def wire(
    *,
    root="3",
    code=0,
    writer=WRITER,
    matrix=IDENTITY,
    words_prefix=(0, 2, 4),
    extra_root=b"",
    body=None,
    suffix=b"",
    parent=b"\0",
    revision=51,
):
    payload = (
        b"\xbe"
        + blob(b"<none>")
        + blob(writer)
        + blob(b"<none>")
        + blob(b"<none>")
        + b"\1"
        + struct.pack("<16f", *matrix)
        + struct.pack("<I", revision)
        + b"\0"
        + struct.pack("<4I", *words_prefix, code)
        + blob(b"")
        + blob(bytes(range(16)))
        + blob(bytes(range(16, 32)))
        + blob(b"<none>")
        + bytes(2)
        + blob(f"<none>{revision};".encode())
        + b"\0"
        + blob(bytes(24))
        + bytes(48)
    )
    first = b"[" + struct.pack("<I", len(payload) - 2) + payload + b"]"
    length = b"" if root is None else options(f"length=`{root}`")
    return packed(
        first
        + b"h\0"
        + length
        + extra_root
        + (sheet() if body is None else body)
        + suffix
        + b"\1"
        + terminal(revision)
        + b"z",
        parent=parent,
    )


def read(data):
    return ed.read(data).read_drawing(user_data_profile=PROFILE)


@pytest.mark.parametrize(
    "root,code,unit,scale",
    [
        ("3", 0, "millimeter", 0.001),
        ("4", 1, "centimeter", 0.01),
        ("5", 2, "meter", 1.0),
        ("8", 3, "inch", 0.0254),
    ],
)
@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed"])
def test_verified_pairs_preserve_exact_sources_and_do_not_convert_geometry(
    root, code, unit, scale, wrapper, zip_factory
):
    data = wire(root=root, code=code)
    if wrapper != "raw":
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    d = doc.read_drawing(user_data_profile=PROFILE)
    p = d.summary.drawing_plane_profile
    assert isinstance(p, ed.DrawingPlaneProfile)
    assert isinstance(p.root_length, ed.DrawingLengthOption)
    assert isinstance(p.header_unit, ed.DrawingHeaderUnit)
    assert p.profile == "edrawings_dxf_34_4_xy_v1"
    assert p.status == "complete" and p.reason is None
    assert (p.source_length_unit, p.source_units_to_meters) == (unit, scale)
    assert (p.stored_xy_unit, p.xy_meters_per_saved_unit) == ("meter", 1)
    assert p.cad_origin == "unavailable"
    assert p.z_semantics == "uninterpreted_drawing_depth"
    assert p.root_length.raw_value == root and p.header_unit.raw_value == code
    assert d.source_bytes(p.root_length.source) == root.encode()
    assert d.source_bytes(p.header_unit.source) == struct.pack("<I", code)
    assert p.root_length.source_record_id in {
        r.source_record_id for r in d.summary.user_option_records
    }
    header = next(
        r for r in d.summary.scene.hsf.records if r.id == p.header_unit.source_record_id
    )
    words = next(f.source for f in header.user_data.fields if f.label == "opaque_words")
    assert p.header_unit.source.offset == words.offset + 12
    primitive = d.summary.scene.primitives[0]
    assert d.primitive_points(primitive.id).data == LINE[1:]
    assert d.summary.scene.units is None
    assert d.summary.scene.placement_status == "unsupported"
    assert d.summary.assessment.status == "partial"
    assert not d.summary.scene.primitive_instances
    assert d.summary.to_dict() == json.loads(
        _core.read_bytes(data, "{}")
        .read_drawing(user_data_profile=PROFILE)
        .summary_json()
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        p.root_length.raw_value = "5"
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.read_drawing(mode="strict", user_data_profile=PROFILE)


@pytest.mark.parametrize(
    "root,code",
    [
        ("3", 1),
        ("4", 0),
        ("8", 8),
        ("0", 0),
        ("03", 0),
        ("9", 4),
        ("-1", 0),
        ("3", 0xFFFFFFFF),
    ],
)
def test_unseen_or_conflicting_unit_pair_keeps_raw_fields(root, code):
    p = read(wire(root=root, code=code)).summary.drawing_plane_profile
    assert p.reason == "drawing.plane_unit_pair_unverified"
    assert p.root_length.raw_value == root and p.header_unit.raw_value == code
    assert p.source_length_unit is None and p.stored_xy_unit is None
    assert p.xy_meters_per_saved_unit is None and p.source_units_to_meters is None


@pytest.mark.parametrize(
    "extra", [options("length=3"), options("LENGTH=8"), options("length=3,length=3")]
)
def test_duplicate_root_length_never_picks_first_or_last(extra):
    p = read(wire(extra_root=extra)).summary.drawing_plane_profile
    assert p.reason == "drawing.plane_length_ambiguous"
    assert p.root_length is None and p.header_unit.raw_value == 0


@pytest.mark.parametrize(
    "extra", [b"", options("length"), options("length=3,broken=`")]
)
def test_missing_or_implicit_or_partial_root_unit(extra):
    p = read(wire(root=None, extra_root=extra)).summary.drawing_plane_profile
    assert p.reason == "drawing.plane_length_unavailable"


@pytest.mark.parametrize(
    "writer", [b"Other Reader", b"DXF/DWG Reader AddIn (34.4.1.0004)"]
)
def test_different_writer_does_not_inherit_unit_semantics(writer):
    p = read(wire(writer=writer)).summary.drawing_plane_profile
    assert p.reason == "drawing.plane_writer_unverified"
    assert p.root_length.raw_value == "3" and p.header_unit.raw_value == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"matrix": (0.0,) * 16},
        {"matrix": (*IDENTITY[:12], 2.0, 0.0, 0.0, 1.0)},
        {"words_prefix": (0, 2, 5)},
    ],
)
def test_private_header_variant_is_unverified(kwargs):
    p = read(wire(**kwargs)).summary.drawing_plane_profile
    assert p.reason == "drawing.plane_header_unverified"


def test_all_records_and_domains_required_but_partial_placement_is_allowed():
    good = read(wire())
    assert good.summary.scene.status == "partial"
    assert good.summary.drawing_plane_profile.status == "complete"
    for data in [wire(suffix=b"\xfe"), wire(parent=b"\0trailing")]:
        assert (
            read(data).summary.drawing_plane_profile.reason
            == "drawing.plane_incomplete"
        )
    assert read(wire(revision=48)).summary.drawing_plane_profile.status == "unsupported"
    assert (
        ed.read(wire()).read_drawing().summary.drawing_plane_profile.status
        == "unsupported"
    )


def matrix_record():
    # HSF stores the first three columns of a 4x4 modelling matrix.
    return b"%" + struct.pack("<12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0)


def test_primitive_ancestor_transform_rejected_even_when_identity():
    data = wire(body=sheet(body=view(body=matrix_record() + LINE)))
    assert (
        read(data).summary.drawing_plane_profile.reason
        == "drawing.plane_transform_unverified"
    )
    # Native writer's identity 3dmodel sibling does not transform 2d geometry.
    body = sheet(
        body=group(
            "view0",
            options("name=View")
            + group("3dmodel", matrix_record())
            + group("2dmodel", LINE),
        )
    )
    assert read(wire(body=body)).summary.drawing_plane_profile.status == "complete"


def test_geometry_outside_sheet_and_missing_structure_are_unverified():
    assert (
        read(wire(body=LINE + sheet())).summary.drawing_plane_profile.reason
        == "drawing.plane_geometry_unverified"
    )
    assert (
        read(wire(body=LINE)).summary.drawing_plane_profile.reason
        == "drawing.plane_geometry_unverified"
    )


def test_exact_shared_output_budget():
    data = wire()
    d = read(data)
    used = d.summary.scene.usage.output_bytes
    assert (
        ed.read(data, limits=ed.Limits(max_output_bytes=used))
        .read_drawing(user_data_profile=PROFILE)
        .summary
        == d.summary
    )
    with pytest.raises(ed.LimitExceededError):
        ed.read(data, limits=ed.Limits(max_output_bytes=used - 1)).read_drawing(
            user_data_profile=PROFILE
        )


def test_cli_and_native_fixture_preserve_unit_boundaries(tmp_path):
    path = tmp_path / "drawing.hsf"
    path.write_bytes(wire())
    output = subprocess.run(
        [
            sys.executable,
            "-m",
            "edrawings_kit",
            "drawing",
            str(path),
            "--user-data-profile",
            PROFILE,
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert (
        json.loads(output.stdout)
        == ed.read_file(path, read_metadata=False)
        .read_drawing(user_data_profile=PROFILE)
        .summary.to_dict()
    )
    fixture = Path(__file__).parent / "fixtures/native-m4/two-layouts-visible-mm.edrw"
    p = (
        ed.read_file(fixture)
        .read_drawing(user_data_profile=PROFILE)
        .summary.drawing_plane_profile
    )
    assert p.status == "complete" and p.source_length_unit == "millimeter"
