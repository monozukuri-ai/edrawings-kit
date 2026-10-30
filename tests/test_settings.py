"""Source-backed settings, inheritance, malformed input and native projection."""

import io
import json
import struct
import subprocess
import sys
import zipfile

import edrawings_kit as ed
import pytest
from test_user_data_audit import sample
from test_views import POINTS, PROFILE, compressed, raw

EDGE = b"\x0e" + struct.pack("<fB", -2, 4)
NAMED = b"@\xff\x03a\0b"
CLIP = b"O\x01" + struct.pack("<i9f", 3, 0, 0, 0, 1, 0, 0, 0, 1, 0)
INDEX = b"n" + struct.pack("<5i", 2, -2, 7, 123, -456)
DEPTH = b"R" + struct.pack("<4I2f", 0x80000000, 16, 0, 16, 0, 0.001)
LOCKS = b"R" + struct.pack("<6I", 0x100000, 0x100000, 4, 4, 0x077F7F7F, 0x077F7F7F)
LOCKS += b"\xff\x01\xff\x01" * 18


@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
def test_settings_sources_and_typed_metadata(wrapper):
    body = EDGE + NAMED + b"-\x02\0\x0d\x03\0*\x10" + CLIP + INDEX + DEPTH + LOCKS
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    if wrapper in ("zip", "prefixed"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("eModel", data)
        data = stream.getvalue()
        if wrapper == "prefixed":
            from conftest import PREFIX

            data = PREFIX + data
    doc = ed.read(data)
    parsed = doc.parse_hsf(mode="strict")
    records = {r.kind: r for r in parsed.summary.records}
    marker = records["marker_symbol"].named_style
    assert isinstance(marker, ed.NamedStyleLayout) and marker.index is None
    assert parsed.source_bytes(marker.name) == b"a\0b"
    assert records["line_pattern"].named_style.index == 2
    assert records["edge_pattern"].named_style.index == 3
    assert records["text_alignment"].value == 0x10
    clip = records["clip_region"].clip_region
    assert isinstance(clip, ed.ClipRegionLayout)
    assert clip.point_count == 3 and clip.options == 1
    assert parsed.source_bytes(clip.points) == CLIP[6:]
    index = records["user_index"].user_index
    assert isinstance(index, ed.UserIndexLayout)
    assert struct.unpack("<2i", parsed.source_bytes(index.indices)) == (-2, 7)
    assert struct.unpack("<2i", parsed.source_bytes(index.values)) == (123, -456)
    options = [r for r in parsed.summary.records if r.opcode == ord("R")]
    assert options[0].rendering.mask == 0x1080000000
    assert options[0].rendering.value == 0x1000000000
    assert len(options[1].rendering.fields) == 40
    assert parsed.source_bytes(options[1].source) == LOCKS
    scene = doc.read_scene()
    assert scene.summary.nodes[0].display.edge_weight.value == ed.MarkerSize(
        2, "pixels"
    )
    assert scene.summary.user_indices[0].layout == index
    assert isinstance(scene.summary.user_indices[0], ed.UserIndices)
    assert scene.source_bytes(scene.summary.user_indices[0].source) == INDEX
    assert len(scene.summary.rendering_options) == 7
    assert scene.summary.processed_records == len(parsed.summary.records)
    assert scene.summary.placement_status == "unsupported"
    with pytest.raises(ed.UnsupportedFeatureError, match="effects are not evaluated"):
        doc.read_scene(mode="strict")


@pytest.mark.parametrize("record", [EDGE, NAMED, CLIP, INDEX, DEPTH, LOCKS])
def test_each_truncation_is_invalid_in_both_modes(record):
    for end in range(len(record)):
        for mode in ("strict", "partial"):
            with pytest.raises(ed.InvalidFormatError):
                ed.read(raw(record[:end])).parse_hsf(mode=mode)


@pytest.mark.parametrize(
    "record,code",
    [
        (b"O\x80", "hsf.clip_region_options"),
        (b"R" + struct.pack("<2I", 0x18000000, 0), "hsf.rendering_options_mask"),
        (
            # Third word (TKO_Rendo_Extended2) selecting contour options, whose
            # operand position is unverified.
            b"R" + struct.pack("<6I", 0x80000000, 0x80000000, 8, 0, 0, 8),
            "hsf.rendering_options_mask",
        ),
        (
            b"R" + struct.pack("<6I", 0x100000, 0x100000, 4, 4, 0x80000000, 0),
            "hsf.rendering_color_lock_mask",
        ),
        (b"\x0e" + struct.pack("<fB", -1, 255), "hsf.edge_weight_units"),
    ],
)
def test_unknown_layout_stops_at_original_opcode(record, code):
    doc = ed.read(raw(record + b"h\x01\0"))
    h = doc.parse_hsf()
    assert not h.summary.records
    assert h.summary.diagnostics[0].code == code
    assert h.source_bytes(h.summary.unparsed[0]) == record + b"h\x01\0"
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.parse_hsf(mode="strict")


def test_counts_names_floats_and_output_limits():
    for body, limits, code in [
        (CLIP, ed.Limits(max_hsf_vertices=2), "hsf.limit_vertices"),
        (INDEX, ed.Limits(max_hsf_records=1), "hsf.limit_user_indices"),
        (NAMED, ed.Limits(max_hsf_string_bytes=2), "hsf.limit_string"),
        (LOCKS, ed.Limits(max_output_bytes=8192), "budget.output"),
    ]:
        with pytest.raises(ed.LimitExceededError) as error:
            ed.read(raw(body + b"\0"), limits=limits).parse_hsf()
        assert error.value.diagnostic.code == code
    for body in [
        b"n" + struct.pack("<i", -1),
        b"O\0" + struct.pack("<i", -1),
        b"\x0e" + struct.pack("<f", float("inf")),
        CLIP[:6] + struct.pack("<f", float("nan")) + CLIP[10:],
        DEPTH[:17] + struct.pack("<2f", float("nan"), 1),
    ]:
        with pytest.raises(ed.InvalidFormatError):
            ed.read(raw(body + b"\0")).parse_hsf()


def test_edge_weight_and_user_indices_do_not_create_geometry_or_erase_tags():
    # Metadata has no generic rendering effect and preserves signed values/duplicates.
    doc = ed.read(raw(b"(\x01a" + EDGE + INDEX + b")q<\x01a\0"))
    scene = doc.read_scene(mode="strict")
    assert scene.summary.status == "complete" and not scene.summary.meshes
    assert scene.summary.references[0].target_id == scene.summary.nodes[1].id
    assert scene.summary.user_indices[0].node_id == scene.summary.nodes[1].id
    assert scene.summary.user_indices[0].interpretation_status == "unsupported"
    body = EDGE + b"(\x01al" + POINTS + b")<\x01a\0"
    scene = ed.read(raw(body)).read_scene(mode="strict")
    assert len(scene.summary.primitive_instances) == 2
    for instance in scene.summary.primitive_instances:
        assert instance.display.edge_weight.value == ed.MarkerSize(2, "pixels")


def test_user_data_and_cli_settings_are_conservative(tmp_path):
    doc = ed.read(compressed(sample() + b"h\0" + EDGE + LOCKS + b"z"))
    scene = doc.read_scene(user_data_profile=PROFILE)
    assert len(scene.summary.opaque_user_data) == 1
    assert len(scene.summary.rendering_options) == 1
    assert scene.summary.placement_status == "unsupported"
    assert not scene.summary.instances and not scene.summary.primitive_instances
    assert doc.read_scene().summary.processed_records == 3
    path = tmp_path / "settings.hsf"
    path.write_bytes(raw(EDGE + NAMED + INDEX + DEPTH + b"\0"))
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path)],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    summary = json.loads(run.stdout)
    assert summary["nodes"][0]["display"]["edge_weight"]["value"]["units"] == "pixels"
    assert summary["user_indices"][0]["layout"]["count"] == 2
    assert summary["rendering_options"][1]["kind"] == "rendering_options"
