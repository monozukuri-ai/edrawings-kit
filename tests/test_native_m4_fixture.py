"""A self-authored fixture saved and reopened by the official 2026 Reader.

These offline tests qualify parser framing, not a fresh native runtime run.
"""

import hashlib
import json
import math
import struct
import subprocess
import sys
from pathlib import Path

import edrawings_kit as ed
import pytest

FIXTURE = Path(__file__).parent / "fixtures/native-m4/two-layouts-mm.edrw"
SHA256 = "d601dbac0130f4084800ab3cdbeb5e15d4ce8f7992a3c360b0b8d6936fc70632"


def test_official_2026_dxf_export_revision51_header_and_source():
    data = FIXTURE.read_bytes()
    assert hashlib.sha256(data).hexdigest() == SHA256
    doc = ed.read(data)
    assert doc.inspect_hsf().header.version == "19.10"
    assert doc.parse_hsf().summary.domains[1].parsed_bytes == 0
    parsed = doc.parse_hsf(user_data_profile="edrawings_be_envelope_v1")
    record = parsed.summary.records[3]
    u = record.user_data
    assert u.profile == "edrawings-first-be-v2-hsf-19.10-revision-51"
    assert (u.declared_length, u.computed_payload_length) == (302, 303)
    assert record.source.length == 309
    fields = {f.label: parsed.source_bytes(f.source) for f in u.fields}
    assert fields["internal_revision"] == struct.pack("<I", 51)
    assert fields["revision_string_candidate"] == b"<none>51;"
    assert fields["leading_string_1"] == b"DXF/DWG Reader AddIn (34.4.1.0003)"
    assert len(fields["revision_tail"]) == 48
    assert parsed.summary.records[4].source.offset == 309
    assert parsed.summary.records[4].view is not None
    # Reading this exact file in the official Reader does not validate every
    # possible payload or the product semantics of the private fields.
    assert not u.native_reader_verified
    visibility = parsed.summary.records[11]
    assert visibility.visibility.mask == 0x07FFFFFF
    assert visibility.visibility.value == 0
    assert visibility.source.offset == 419 and visibility.source.length == 9
    assert parsed.source_bytes(visibility.source) == bytes.fromhex("56ff00ffff00000700")
    assert parsed.summary.records[12].source.offset == 428
    clip = parsed.summary.records[16]
    assert clip.source.offset == 522 and clip.source.length == 66
    assert clip.clip_region.options == 5 and clip.clip_region.point_count == 5
    assert parsed.summary.records[17].source.offset == 588
    drawing = doc.read_drawing(user_data_profile="edrawings_be_envelope_v1")
    assert drawing.summary.assessment.status == "partial"
    assert drawing.summary.scene.placement_status == "unsupported"
    assert not drawing.summary.scene.primitive_instances
    assert "hsf.visibility_geometry_bit26" in [
        d.code for d in drawing.summary.scene.diagnostics
    ]
    with pytest.raises(ed.UnsupportedFeatureError, match="hsf.experimental_user_data"):
        doc.parse_hsf(mode="strict", user_data_profile="edrawings_be_envelope_v1")


@pytest.mark.parametrize(
    "filename,sha256,counts,stored_z",
    [
        (FIXTURE.name, SHA256, (573, 92, 80), 1.0),
        (
            "two-layouts-visible-mm.edrw",
            "8c730618130c26dbe628e0aa3767e4d3a220444e76556c4cf49f475f1f52ca11",
            (592, 97, 74),
            2.0,
        ),
        (
            "two-layouts-japanese-mm.edrw",
            "3de42bf9aa6424678e3e919562573dfe89593f1ce878efde733ca4bc89516fc1",
            (593, 97, 74),
            2.0,
        ),
    ],
)
def test_native_fixture_full_inventory_and_known_relative_geometry(
    filename, sha256, counts, stored_z
):
    path = FIXTURE.parent / filename
    assert hashlib.sha256(path.read_bytes()).hexdigest() == sha256
    drawing = ed.read_file(path).read_drawing(
        user_data_profile="edrawings_be_envelope_v1",
        image_profile="edrawings_1910_u32_v1",
    )
    s = drawing.summary.scene
    assert s.processed_records == len(s.hsf.records) == counts[0]
    assert not s.hsf.unparsed
    assert (len(s.nodes), len(s.primitives)) == counts[1:] and not s.meshes
    assert len(s.opaque_user_data) == 2
    assert s.hsf.records[-3].user_data.profile.endswith("revision-51")
    if filename == "two-layouts-japanese-mm.edrw":
        texts = [p.text for p in s.primitives if p.text]
        assert len(texts) == 1
        assert texts[0].value == "寸法確認 100 mm"
        assert texts[0].encoding == "utf_8" and texts[0].encoding_code == 10
        assert texts[0].status == "complete"
    else:
        assert not any(p.text for p in s.primitives)
    nodes = {n.id: n for n in s.nodes}
    options = {}
    for record in drawing.summary.user_option_records:
        assert record.parsing_status == "complete"
        options.setdefault(record.node_id, {}).update(
            (a.name, a.value) for a in record.assignments
        )
    expected_names = {"sheet0": "Model", "sheet1": "M4_SHEET_A", "sheet2": "M4_SHEET_B"}
    assert {
        n.name: options[n.id]["name"] for n in s.nodes if n.name in expected_names
    } == expected_names
    # Source node order is sheet2, sheet1, sheet0; it is not native SheetIndex.
    assert [n.name for n in s.nodes if n.name in expected_names] == [
        "sheet2",
        "sheet1",
        "sheet0",
    ]
    groups = {}
    for p in s.primitives:
        ancestors = []
        cursor = p.owner_node_id
        while cursor:
            ancestors.append(nodes[cursor])
            cursor = nodes[cursor].parent_id
        if not any(
            options.get(n.id, {}).get("layername") == "M4_MODEL" for n in ancestors
        ):
            continue
        sheet = next(n.name for n in ancestors if n.name in expected_names)
        groups.setdefault(sheet, {})[p.kind] = p
    assert set(groups) == set(expected_names)
    # Independently authored dimensions and viewport scales. This observed
    # numeric ratio is not a general saved-unit or absolute-projection claim.
    for sheet, scale in [("sheet0", 1.0), ("sheet1", 1.375), ("sheet2", 1.625)]:
        group = groups[sheet]
        assert set(group) == {"polyline", "circle"}

        def points(p):
            return list(struct.iter_unpack("<3f", drawing.primitive_points(p.id).data))

        rectangle, circle = points(group["polyline"]), points(group["circle"])
        assert len(rectangle) == 5 and rectangle[0] == rectangle[-1]
        # All XY coordinates are <0.25, so float32 ULP is <=1.49e-8.
        # 5e-8 accommodates rounding of two endpoints and length arithmetic.
        assert math.dist(rectangle[0], rectangle[1]) == pytest.approx(
            0.1 * scale, abs=5e-8, rel=0
        )
        assert math.dist(rectangle[1], rectangle[2]) == pytest.approx(
            0.05 * scale, abs=5e-8, rel=0
        )
        assert math.dist(circle[0], circle[2]) / 2 == pytest.approx(
            0.01 * scale, abs=5e-8, rel=0
        )
        # Z changed from 1 to 2 on the corrected native export, despite the
        # same planar source geometry. Do not call this a physical XYZ unit.
        assert all(p[2] == stored_z for p in rectangle + circle)
    assert s.placement_status == "unsupported"


def test_japanese_native_text_source_and_cli_agree():
    path = FIXTURE.parent / "two-layouts-japanese-mm.edrw"
    drawing = ed.read_file(path, read_metadata=False).read_drawing(
        user_data_profile="edrawings_be_envelope_v1"
    )
    text_primitive = next(p for p in drawing.summary.scene.primitives if p.text)
    value = text_primitive.text
    assert text_primitive.source_record_id == "entry:0/record:521"
    assert value.source.domain_id == "entry:0/hsf:1"
    assert (value.source.offset, value.source.length) == (10169, 19)
    # Expected wire bytes are independent of either Rust or Python decoding.
    assert drawing.source_bytes(value.source) == bytes.fromhex(
        "e5afb8e6b395e7a2bae8aa8d20313030206d6d"
    )
    result = subprocess.run(
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
    assert json.loads(result.stdout) == drawing.summary.to_dict()
    assert "hsf.text_encoding" not in {
        d.code for d in drawing.summary.scene.diagnostics
    }
