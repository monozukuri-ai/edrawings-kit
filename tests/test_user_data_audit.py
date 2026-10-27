"""Audit-tool robustness, using invented bytes rather than bundled CAD files.

These fixtures test framing/limits, not the truth of the empirical layout.
The reference reader is independent of the Rust parser.
"""

import hashlib
import importlib.util
import struct
import zlib
from pathlib import Path

import pytest

SPEC = importlib.util.spec_from_file_location(
    "audit_user_data",
    Path(__file__).resolve().parents[1] / "tests/helpers/user_data_reference.py",
)
assert SPEC is not None and SPEC.loader is not None
audit = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit)


def blob(value):
    return bytes([len(value)]) + value


def sample(
    revision=46, delta=2, *, modern=True, first_string=b"]h\x00", include_path=b""
):
    # Strings and opaque bytes deliberately contain apparent stop markers/opcodes.
    payload = (
        b"\xbe"
        + blob(first_string)
        + blob(b"writer")
        + blob(b"")
        + blob(b"\xff\x80")
        + b"\x01"
        + struct.pack("<16f", *([0.0] * 16))
        + struct.pack("<I", revision)
        + b"\x00"
        + b"]" * 16
        + blob(include_path)
        + blob(bytes(range(16)))
        + blob(bytes(range(16, 32)))
        + blob(b"config")
        + b"\x00\x01"
        + blob(f"{revision};".encode())
        + b"\x00"
        + blob(b"]" * 24)
        + (b"T" * 12 + struct.pack("<8f", *range(8)) if modern else b"")
        + bytes(4)
    )
    return b"[" + struct.pack("<I", len(payload) - delta) + payload + b"]"


def view(*, flags=0, name=b"default", width=10.0):
    return (
        b"}"
        + bytes([flags])
        + struct.pack("<11f", 0, 0, 1, 0, 0, 0, 0, 1, 0, width, 20)
        + b"".join(struct.pack("<f", 2.0) for bit in (4, 8, 16) if flags & bit)
        + blob(name)
    )


def font(*, length=0):
    return b"f\x00" + blob(b"enfield") + b"\x05\x00" + struct.pack("<i", length)


@pytest.mark.parametrize(
    "version,revision,delta,modern",
    [
        ("8.05", 22, 1, False),
        ("14.50", 39, 1, True),
        ("19.10", 45, 2, True),
        ("19.10", 46, 2, True),
        ("19.10", 48, 2, True),
        ("19.10", 51, 2, True),
    ],
)
def test_boundary_ranges_hashes_and_every_truncation(version, revision, delta, modern):
    data = sample(
        revision,
        delta,
        modern=modern,
        include_path=b"/include/test" if delta == 1 else b"",
    )
    result = audit.inspect_header(data + view() + b"h\x00", version)
    assert result["computed_stop_offset"] == len(data) - 1
    assert result["next_record_offset"] == len(data)
    assert result["computed_payload_length"] == len(data) - 6
    assert result["declared_length"] == len(data) - 6 - delta
    assert result["leading_strings_ascii"][3] is None
    assert result["general_format_rule_verified"] is False
    assert result["native_reader_verified"] is False
    at = 0
    for field in result["fields"]:
        assert field["offset"] == at
        raw = data[at : at + field["length"]]
        assert field["sha256"] == hashlib.sha256(raw).hexdigest()
        at += field["length"]
    assert at == len(data)
    for end in range(len(data)):
        with pytest.raises(audit.ProfileMismatch):
            audit.inspect_header(data[:end], version)


def test_variable_fields_move_boundary_and_marker_search_is_never_used():
    a = sample(first_string=b"x")
    b = sample(first_string=b"x" * 17 + b"]h\x00")
    assert audit.inspect_header(b, "19.10")["next_record_offset"] == len(b)
    assert len(b) - len(a) == 19
    # Plausible later suffixes cannot repair a missing stop or incorrect size.
    with pytest.raises(audit.ProfileMismatch, match="No Stop"):
        audit.inspect_header(b[:-1] + b"x]" + view() + b"h\x00", "19.10")
    broken = bytearray(b)
    struct.pack_into("<I", broken, 1, len(b) - 6)
    with pytest.raises(audit.ProfileMismatch, match="length relation"):
        audit.inspect_header(bytes(broken) + b"]" + view() + b"h\x00", "19.10")


@pytest.mark.parametrize("include_path,delta", [(b"", 2), (b"x", 1), (b"x" * 32, 1)])
def test_same_revision_uses_conditional_length_accounting(include_path, delta):
    data = sample(46, delta, include_path=include_path)
    b = audit.inspect_header(data, "19.10")
    assert b["observed_length_delta"] == delta
    assert b["next_record_offset"] == len(data)
    assert b["length_accounting"]["include_path_bytes"] == len(include_path)
    assert b["length_accounting"]["writer_implementation_verified"] is False
    # Do not silently accept either +1 or +2: the parsed field determines it.
    wrong_delta = 1 if delta == 2 else 2
    corrupt = sample(46, wrong_delta, include_path=include_path)
    with pytest.raises(audit.ProfileMismatch, match="length relation"):
        audit.inspect_header(corrupt, "19.10")


def test_nonempty_include_changes_actual_and_declared_lengths_differently():
    empty = audit.inspect_header(sample(), "19.10")
    full = audit.inspect_header(sample(delta=1, include_path=b"x" * 32), "19.10")
    assert full["computed_payload_length"] - empty["computed_payload_length"] == 32
    assert full["declared_length"] - empty["declared_length"] == 33


@pytest.mark.parametrize(
    "label,replacement,reason",
    [
        ("start", b"x", "Not Start"),
        ("private_identifier", b"\xbf", "0xBE"),
        ("declared_length", b"\xff" * 4, "bounded header"),
        ("leading_string_0_length", b"\xff", "truncated"),
        ("flag_0", b"\x02", "flag_0"),
        ("flag_1", b"\xff", "flag_1"),
        ("internal_revision", struct.pack("<I", 47), "Unverified HSF/revision"),
        ("matrix_candidate", struct.pack("<f", float("nan")), "nonfinite"),
        ("opaque_blob_0_length", b"\x0f", "unverified length"),
        ("opaque_blob_1_length", b"\x11", "unverified length"),
        ("opaque_blob_2_length", b"\x00", "unverified length"),
        ("revision_string_candidate", b"99;", "do not corroborate"),
    ],
)
def test_reject_unverified_or_broken_profiles(label, replacement, reason):
    data = bytearray(sample())
    fields = audit.inspect_header(bytes(data), "19.10")["fields"]
    at = next(f["offset"] for f in fields if f["label"] == label)
    data[at : at + len(replacement)] = replacement
    with pytest.raises(audit.ProfileMismatch, match=reason):
        audit.inspect_header(bytes(data), "19.10")


def test_unknown_version_tail_finiteness_and_header_byte_budget(monkeypatch):
    data = sample()
    with pytest.raises(audit.ProfileMismatch, match="Unverified HSF/revision"):
        audit.inspect_header(data, "20.00")
    # The 8-float tail contains infinity, without altering length or stop position.
    corrupt = data[:-9] + struct.pack("<f", float("inf")) + data[-5:]
    with pytest.raises(audit.ProfileMismatch, match="nonfinite"):
        audit.inspect_header(corrupt, "19.10")
    monkeypatch.setattr(audit, "MAX_HEADER_BYTES", len(data) - 1)
    with pytest.raises(audit.ProfileMismatch):
        audit.inspect_header(data, "19.10")


def test_following_records_have_independent_exact_ranges():
    data = view(flags=0x1C) + font() + b"(\x05sheet)qU\xff\xff\x03\0\0\0abc!"
    result = audit.following_prefix(data, 0)
    records = result["records"]
    assert [r["kind"] for r in records] == [
        "view",
        "font",
        "open_segment",
        "close_segment",
        "tag_implicit",
        "user_options",
    ]
    assert [r["length"] for r in records] == [66, 16, 7, 1, 1, 10]
    assert [r["offset"] for r in records] == [0, 66, 82, 89, 90, 91]
    assert records[0]["name_ascii"] == "default"
    assert records[1]["data_bytes"] == 0 and records[1]["encoding"] == 5
    assert result["end"] == 101 and result["stop_opcode"] == ord("!")
    assert result["open_depth_at_stop"] == 0


@pytest.mark.parametrize(
    "record",
    [
        view(),
        view(flags=0x1C),
        font(),
        b"h\x01",
        b"+" + struct.pack("<f", 0.5),
        b"+" + struct.pack("<f", -2) + b"\x04",
    ],
)
def test_every_following_record_truncation(record):
    assert len(audit.following_prefix(record, 0)["records"]) == 1
    for end in range(len(record)):
        result = audit.following_prefix(record[:end], 0)
        assert result["records"] == [] and result["end"] == 0


@pytest.mark.parametrize(
    "data,reason",
    [
        (b"h\x02", "Unknown handedness"),
        (b"}\xff", "Unknown projection"),
        (view(width=0), "Non-positive"),
        (view(width=float("nan")), "nonfinite"),
        (b")", "Unbalanced close"),
        (font(length=-1), "truncated or audit byte limit"),
        (font(length=2**31 - 1), "truncated or audit byte limit"),
        (b"f\x01", "Unimplemented font"),
        (b"U\xff\xff\xff\xff\xff\xff", "truncated or audit byte limit"),
        (b"!", "unimplemented_opcode_0x21"),
        (b"+" + struct.pack("<f", float("inf")), "nonfinite"),
        (b"+" + struct.pack("<f", -2) + b"\x05", "Unknown marker size units"),
    ],
)
def test_invalid_following_record_does_not_resynchronize(data, reason):
    result = audit.following_prefix(data + view() + b"h\x00", 0)
    assert result["records"] == [] and result["end"] == 0
    assert reason in result["stop_reason"]


def test_following_limits_and_invalid_start(monkeypatch):
    result = audit.following_prefix(b"q" * 1000, 0)
    assert len(result["records"]) == 64
    assert result["stop_reason"] == "audit_record_limit"
    monkeypatch.setattr(audit, "MAX_FOLLOWING_BYTES", 2)
    result = audit.following_prefix(b"h\x00q", 0)
    assert len(result["records"]) == 1 and result["end"] == 2
    assert "audit byte limit" in result["stop_reason"]
    for start in (-1, 4):
        with pytest.raises(audit.ProfileMismatch, match="cursor range"):
            audit.following_prefix(b"abc", start)


def container_bytes(body, version=b"19.10"):
    return (
        b";; HSF V"
        + version
        + b" \nI\x04\0\0\0B\0"
        + struct.pack("<6f", -1, -1, -1, 1, 1, 1)
        + b"Z"
        + zlib.compress(body + view() + b"h\x00z")
        + b"\0"
    )
