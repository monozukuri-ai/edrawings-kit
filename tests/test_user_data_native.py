"""Compiled Rust/PyO3 contract checks using independently invented audit fixtures."""

import json
import struct
import subprocess
import sys

import edrawings_kit as ed
import pytest
from test_user_data_audit import audit, container_bytes, sample

PROFILE = "edrawings_first_be_v2"


@pytest.mark.parametrize(
    "version,rev",
    [
        ("8.05", 22),
        ("14.50", 39),
        ("19.10", 45),
        ("19.10", 46),
        ("19.10", 48),
        ("19.10", 51),
    ],
)
@pytest.mark.parametrize("include", [b"", b"/include/model"])
def test_native_fields_agree_with_independent_auditor(version, rev, include):
    block = sample(rev, 1 + int(not include), modern=rev != 22, include_path=include)
    expected = audit.inspect_header(block, version)
    doc = ed.read(container_bytes(block, version.encode()))
    parsed = doc.parse_hsf(user_data_profile=PROFILE)
    r = parsed.summary.records[3]
    u = r.user_data
    assert isinstance(u, ed.UserDataLayout)
    assert parsed.summary.stages.hsf_syntax == "partial"
    assert u.evidence_level == "empirical_corpus_layout"
    assert u.native_reader_verified is False
    assert u.declared_length == expected["declared_length"]
    assert u.computed_payload_length == expected["computed_payload_length"]
    assert parsed.source_bytes(r.source) == block
    for f, expected_field in zip(u.fields, expected["fields"], strict=True):
        assert f.label == expected_field["label"]
        assert f.source.offset == expected_field["offset"]
        assert f.source.length == expected_field["length"]
    assert parsed.summary.domains[1].parsed_bytes == parsed.summary.domains[1].byte_len
    assert parsed.summary.unparsed == ()
    assert parsed.summary.records[4].source.offset == len(block)
    assert parsed.summary.records[4].view is not None
    assert parsed.summary.diagnostics[0].code == "hsf.experimental_user_data"
    assert doc.parse_hsf().summary.domains[1].parsed_bytes == 0
    for method in (doc.parse_hsf, doc.read_scene, doc.read_drawing):
        with pytest.raises(ed.UnsupportedFeatureError) as e:
            method(mode="strict", user_data_profile=PROFILE)
        assert e.value.diagnostic.code == "hsf.experimental_user_data"
    scene = doc.read_scene(user_data_profile=PROFILE)
    assert scene.summary.hsf.to_dict() == parsed.summary.to_dict() | {
        "stages": scene.summary.hsf.stages.to_dict()
    }
    assert not scene.summary.primitive_instances and not scene.summary.instances
    assert "hsf.user_data_inventory" in [d.code for d in scene.summary.diagnostics]
    assert scene.summary.placement_status == "unsupported"
    assert len(scene.summary.views) == 1
    assert scene.summary.nodes[0].world_handedness.value == "left"
    assert (
        doc.read_drawing(user_data_profile=PROFILE).summary.assessment.status
        == "partial"
    )


def test_native_mutations_all_cuts_and_no_fallback():
    block = sample()
    for end in range(1, len(block)):
        p = ed.read(container_bytes(block[:end])).parse_hsf(user_data_profile=PROFILE)
        assert not any(r.user_data for r in p.summary.records)
        assert p.summary.domains[1].parsed_bytes == 0
    fields = audit.inspect_header(block, "19.10")["fields"]
    for label, replacement in [
        ("flag_0", b"\xff"),
        ("flag_1", b"\x02"),
        ("internal_revision", struct.pack("<I", 47)),
        ("matrix_candidate", struct.pack("<f", float("nan"))),
        ("opaque_blob_0_length", b"\x0f"),
        ("opaque_blob_1_length", b"\x0f"),
        ("opaque_blob_2_length", b"\x0f"),
        ("revision_string_candidate", b"99;"),
        ("declared_length", struct.pack("<I", len(block) - 7)),
        ("stop", b"!"),
    ]:
        data = bytearray(block)
        at = next(f["offset"] for f in fields if f["label"] == label)
        data[at : at + len(replacement)] = replacement
        p = ed.read(container_bytes(bytes(data) + b"]")).parse_hsf(
            user_data_profile=PROFILE
        )
        assert p.summary.domains[1].parsed_bytes == 0
        assert p.summary.diagnostics[0].code == "edrawings.user_data_profile_mismatch"


def test_native_profile_cli_and_invalid_option(tmp_path):
    path = tmp_path / "invented.hsf"
    path.write_bytes(container_bytes(sample()))
    for command in ("hsf", "scene", "drawing"):
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "edrawings_kit",
                command,
                str(path),
                "--user-data-profile",
                PROFILE,
            ],
            capture_output=True,
            encoding="utf-8",
        )
        assert result.returncode == 0, result.stderr
        value = json.loads(result.stdout)
        if command == "drawing":
            value = value["scene"]
        if command != "hsf":
            value = value["hsf"]
        assert value["records"][3]["user_data"]["native_reader_verified"] is False
    doc = ed.read(path.read_bytes())
    with pytest.raises(ValueError, match="user_data_profile"):
        doc.parse_hsf(user_data_profile="auto")
