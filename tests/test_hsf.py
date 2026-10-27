import dataclasses
import gc
import hashlib
import json
import subprocess
import sys
import zlib

import edrawings_kit as ed
import pytest
from edrawings_kit import _core

HEADER = b";; HSF V19.10 \n"
DECODED = b"(\x04rootqU\x05\0x=\xff,y)r\0\0\0\0z"
HSF = HEADER + b"I\x04\0\0\0Z" + zlib.compress(DECODED) + b"\0"


@pytest.mark.parametrize("kind", ["raw", "zip", "prefixed"])
def test_native_and_python_schema_agree_and_source_survives_owner(
    kind, zip_factory, tmp_path
):
    raw = (
        HSF
        if kind == "raw"
        else zip_factory([("eModel", HSF)], prefix=kind == "prefixed")
    )
    path = tmp_path / "model.eprt"
    path.write_bytes(raw)
    doc = ed.read_file(path)
    parsed = doc.parse_hsf(mode="strict")
    assert doc.inspection.stages.hsf_syntax == "not_requested"  # operation is immutable
    path.unlink()
    del doc
    gc.collect()
    info = parsed.summary
    native = _core.read_bytes(raw, "{}").parse_hsf(mode="strict")
    assert info.to_dict() == json.loads(native.summary_json())
    assert info.stages.hsf_header == info.stages.hsf_syntax == "complete"
    assert info.stages.scene == info.stages.drawing == "not_requested"
    assert info.unparsed == info.diagnostics == ()
    assert len(info.domains) == 2
    root, decoded = info.domains
    assert root.sha256 == hashlib.sha256(HSF).hexdigest()
    assert decoded.sha256 == hashlib.sha256(DECODED).hexdigest()
    assert parsed.source_bytes(decoded.parent) == zlib.compress(DECODED)
    assert root.parent.domain_id == info.source.domain_id
    assert info.source.file_sha256 == hashlib.sha256(raw).hexdigest()
    option = next(r for r in info.records if r.kind == "user_options")
    assert parsed.source_bytes(option.payload) == b"x=\xff,y"
    with pytest.raises(dataclasses.FrozenInstanceError):
        option.value = 0
    with pytest.raises(ed.InvalidFormatError, match="hsf.invalid_source_range"):
        parsed.source_bytes(ed.HsfSpan(decoded.id, decoded.byte_len, 1))
    with pytest.raises(ed.InvalidFormatError, match="hsf.invalid_source_range"):
        parsed.source_bytes(ed.HsfSpan("missing", 0, 0))


@pytest.mark.parametrize("compressed", [False, True])
@pytest.mark.parametrize("wrapped", [False, True])
def test_partial_and_strict_stop_at_same_opcode_without_scanning(
    compressed, wrapped, zip_factory
):
    commands = b";ok\n\xfeI\0\0\0\0"
    raw = (
        HEADER
        + (b"Z" + zlib.compress(commands + b"z") if compressed else commands)
        + b"\0"
    )
    doc = ed.read(zip_factory([("eModel", raw)]) if wrapped else raw)
    p = doc.parse_hsf()
    info = p.summary
    assert info.stages.hsf_syntax == "partial"
    assert len(info.records) == (2 if compressed else 1)
    diag = info.diagnostics[0]
    assert diag.code == "hsf.unknown_opcode"
    assert diag.classification == "unsupported"
    assert diag.opcode == 0xFE and diag.hsf_version == "19.10"
    assert diag.byte_range.offset == (4 if compressed else len(HEADER) + 4)
    assert diag.domain_id == info.domains[-1].id
    assert len(info.unparsed) == (2 if compressed else 1)
    assert p.source_bytes(info.unparsed[-1]).startswith(b"\xfeI")
    with pytest.raises(ed.UnsupportedFeatureError) as e:
        doc.parse_hsf(mode="strict")
    assert e.value.diagnostic == diag


@pytest.mark.parametrize(
    "body", [b"I\0", b"U\x03\0x", b"(\0\0", b")\0", b"\0x", b"Zinvalid"]
)
@pytest.mark.parametrize("mode", ["strict", "partial"])
def test_corruption_remains_invalid_in_both_modes(body, mode):
    with pytest.raises(ed.InvalidFormatError) as e:
        ed.read(HEADER + body).parse_hsf(mode=mode)
    assert e.value.diagnostic.entry_id == "raw:0"
    assert e.value.diagnostic.domain_id == "raw:0/hsf:0"
    assert e.value.diagnostic.classification == "invalid"


def test_shared_nested_decompression_budget(zip_factory):
    raw = zip_factory([("eModel", HSF)])
    exact = len(HSF) + len(DECODED)
    parsed = ed.read(raw, limits=ed.Limits(max_expanded_bytes=exact)).parse_hsf(
        mode="strict"
    )
    assert parsed.summary.usage.expanded_bytes == exact
    with pytest.raises(ed.LimitExceededError, match="budget.expanded") as e:
        ed.read(raw, limits=ed.Limits(max_expanded_bytes=exact - 1)).parse_hsf()
    assert e.value.diagnostic.domain_id == "entry:0/hsf:0"
    assert e.value.diagnostic.opcode == ord("Z")


def test_hsf_compression_ratio_limit_propagates():
    raw = HEADER + b"Z" + zlib.compress(b";" + b"x" * 1000 + b"\nz") + b"\0"
    with pytest.raises(ed.LimitExceededError, match="hsf.limit_compression_ratio"):
        ed.read(raw, limits=ed.Limits(max_compression_ratio=1)).parse_hsf()


@pytest.mark.parametrize(
    "field",
    [
        "max_hsf_records",
        "max_hsf_domains",
        "max_hsf_segment_depth",
        "max_hsf_string_bytes",
    ],
)
def test_hsf_limits_propagate_and_zero_is_not_unlimited(field):
    limits = dataclasses.replace(ed.Limits(), **{field: 0})
    with pytest.raises(ed.LimitExceededError):
        ed.read(HSF, limits=limits).parse_hsf()


def test_multiple_entries_do_not_collide_and_selection_is_explicit(zip_factory):
    doc = ed.read(zip_factory([("eModel", HSF), ("eModel", HSF)]))
    with pytest.raises(ed.UnsupportedFeatureError, match="hsf.ambiguous_candidates"):
        doc.parse_hsf()
    a, b = (doc.parse_hsf(f"entry:{i}").summary for i in (0, 1))
    assert set(r.id for r in a.records).isdisjoint(r.id for r in b.records)
    assert set(d.id for d in a.domains).isdisjoint(d.id for d in b.domains)
    with pytest.raises(ValueError, match="mode"):
        doc.parse_hsf("entry:0", mode="anything")


def test_user_data_and_unverified_versions_are_explicitly_unsupported():
    parsed = ed.read(HEADER + b"[\x03\0\0\0abc]\0").parse_hsf()
    assert parsed.summary.diagnostics[0].code == "hsf.unsupported_user_data"
    assert not parsed.summary.records
    parsed = ed.read(b";; HSF V20.90 \n\0").parse_hsf()
    assert parsed.summary.diagnostics[0].code == "hsf.unsupported_version"
    assert parsed.summary.stages.hsf_header == "complete"
    assert parsed.summary.stages.hsf_syntax == "partial"


def test_hsf_cli_reports_partial_and_strict_failure(tmp_path):
    path = tmp_path / "sample.hsf"
    path.write_bytes(HEADER + b"\xfe\0")
    args = [sys.executable, "-m", "edrawings_kit", "hsf", str(path)]
    partial = subprocess.run(args, capture_output=True, encoding="utf-8", check=True)
    assert json.loads(partial.stdout)["stages"]["hsf_syntax"] == "partial"
    strict = subprocess.run(
        [*args, "--mode", "strict"], capture_output=True, encoding="utf-8"
    )
    assert strict.returncode == 2
    assert not strict.stdout
    assert json.loads(strict.stderr)["error"]["opcode"] == 254
    path.write_bytes(HSF)
    complete = subprocess.run(
        [*args, "--mode", "strict"], capture_output=True, encoding="utf-8", check=True
    )
    assert json.loads(complete.stdout)["stages"]["hsf_syntax"] == "complete"
