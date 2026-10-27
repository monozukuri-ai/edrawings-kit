"""Independent byte-level reference used by synthetic framing regressions."""

from __future__ import annotations

import hashlib
import math
import struct
from typing import Any

# Only tail sizes depend on the observed HSF/revision pair. The original
# revision-dependent length delta was falsified by an independent revision-46
# file with a nonempty include path. Independent test reference for the stored layout.
PROFILES = {
    ("8.05", 22): 4,
    ("14.50", 39): 48,
    ("19.10", 45): 48,
    ("19.10", 46): 48,
    ("19.10", 48): 48,
    ("19.10", 51): 48,
}
MAX_HEADER_BYTES = 4096
MAX_FOLLOWING_BYTES = 16 << 10
MAX_FOLLOWING_RECORDS = 64


class ProfileMismatch(ValueError):
    """The empirical profile cannot establish a boundary for this input."""


class Cursor:
    def __init__(self, data: bytes, position: int, limit: int):
        if not 0 <= position <= len(data) or limit < position:
            raise ProfileMismatch("Invalid cursor range")
        self.data = data
        self.position = position
        self.limit = min(len(data), limit)
        self.fields: list[dict[str, Any]] = []

    def take(self, label: str, length: int) -> bytes:
        end = self.position + length
        if length < 0 or end > self.limit:
            raise ProfileMismatch(f"{label}: truncated or audit byte limit exceeded")
        data = self.data[self.position : end]
        self.fields.append(
            {
                "label": label,
                "offset": self.position,
                "length": length,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        )
        self.position = end
        return data

    def byte(self, label: str) -> int:
        return self.take(label, 1)[0]

    def u32(self, label: str) -> int:
        return int.from_bytes(self.take(label, 4), "little")

    def blob(self, label: str, expected: int | None = None) -> bytes:
        length = self.byte(label + "_length")
        if expected is not None and length != expected:
            raise ProfileMismatch(f"{label}: unverified length {length}")
        return self.take(label, length)


def finite_floats(data: bytes, label: str) -> tuple[float, ...]:
    values = struct.unpack(f"<{len(data) // 4}f", data)
    if not all(math.isfinite(v) for v in values):
        raise ProfileMismatch(f"{label}: nonfinite values")
    return values


def ascii_candidate(data: bytes) -> str | None:
    return data.decode("ascii") if data.isascii() else None


def inspect_header(data: bytes, version: str) -> dict[str, Any]:
    """Calculate an observed-layout boundary without using declared length to seek.

    Input offset 0 must be the first record of the first decoded HSF domain.
    The caller verifies this context. A match is an empirical layout observation,
    not a general HSF rule or native-reader qualification.
    """
    c = Cursor(data, 0, MAX_HEADER_BYTES)
    if c.byte("start") != ord("["):
        raise ProfileMismatch("Not Start User Data at decoded offset zero")
    declared = c.u32("declared_length")
    if declared > MAX_HEADER_BYTES - 6:
        raise ProfileMismatch("Declared length exceeds the bounded header profile")
    if c.byte("private_identifier") != 0xBE:
        raise ProfileMismatch("Not the observed 0xBE header")
    leading = [c.blob(f"leading_string_{i}") for i in range(4)]
    if c.byte("flag_0") not in (0, 1):
        raise ProfileMismatch("Unverified flag_0")
    finite_floats(c.take("matrix_candidate", 64), "matrix_candidate")
    revision = c.u32("internal_revision")
    profile = PROFILES.get((version, revision))
    if profile is None:
        raise ProfileMismatch(f"Unverified HSF/revision pair: {version}/{revision}")
    if c.byte("flag_1") not in (0, 1):
        raise ProfileMismatch("Unverified flag_1")
    c.take("opaque_words", 16)
    include_name = c.blob("include_path_candidate")
    c.blob("opaque_blob_0", 16)
    c.blob("opaque_blob_1", 16)
    config_name = c.blob("configuration_candidate")
    c.take("opaque_flags", 2)
    revision_text = c.blob("revision_string_candidate")
    if revision_text not in (f"{revision};".encode(), f"<none>{revision};".encode()):
        raise ProfileMismatch("Revision integer and string do not corroborate")
    c.take("opaque_flag", 1)
    c.blob("opaque_blob_2", 24)
    tail_length = profile
    tail = c.take("revision_tail", tail_length)
    if tail_length == 48:
        finite_floats(tail[12:44], "tail_float_candidates")
    end = c.position
    # Inferred accounting: a constant one-byte deficit plus the empty include
    # length byte. 0xBE is a candidate for the constant deficit, but observations
    # cannot identify which constant-size byte the native writer excludes.
    observed_delta = 1 + int(not include_name)
    # This relation is checked AFTER walking the fields; it is not used as a seek.
    if end - 5 - declared != observed_delta:
        raise ProfileMismatch("Computed field boundary disagrees with length relation")
    if c.byte("stop") != ord("]"):
        raise ProfileMismatch("No Stop User Data at the computed field boundary")
    return {
        "profile": f"edrawings-first-be-hsf-{version}-revision-{revision}",
        "evidence_level": "empirical_corpus_layout",
        "general_format_rule_verified": False,
        "native_reader_verified": False,
        "declared_length": declared,
        "computed_payload_length": end - 5,
        "observed_length_delta": observed_delta,
        "declared_end_offset": 5 + declared,
        "computed_stop_offset": end,
        "next_record_offset": end + 1,
        "internal_revision": revision,
        "revision_tail_bytes": tail_length,
        "length_accounting": {
            "model": "constant_byte_deficit_plus_empty_include_length",
            "evidence": "inferred_from_cross_file_length_differences",
            "writer_implementation_verified": False,
            "constant_deficit_bytes": 1,
            "constant_deficit_origin": "unresolved; 0xBE identifier is a candidate",
            "empty_include_length_deficit_bytes": int(not include_name),
            "include_path_bytes": len(include_name),
        },
        "source": {"offset": 0, "length": end + 1},
        "payload": {"offset": 5, "length": end - 5},
        "leading_strings_ascii": [ascii_candidate(b) for b in leading],
        "include_path_candidate_ascii": ascii_candidate(include_name),
        "configuration_candidate_ascii": ascii_candidate(config_name),
        "fields": c.fields,
    }


def following_prefix(data: bytes, start: int) -> dict[str, Any]:
    """Independently frame a bounded suffix using public HSF opcode definitions.

    This deliberately stops at every unimplemented operand. It does not search
    for plausible instructions, claim whole-stream validity, or render anything.
    """
    c = Cursor(data, start, start + MAX_FOLLOWING_BYTES)
    records: list[dict[str, Any]] = []
    depth = 0
    stopped: str | None = None
    for _ in range(MAX_FOLLOWING_RECORDS):
        at = c.position
        try:
            op = c.byte("opcode")
            name: str | None = None
            details: dict[str, Any] = {}
            if op == ord("h"):
                kind = "handedness"
                value = c.byte("handedness")
                if value not in (0, 1):
                    raise ProfileMismatch("Unknown handedness")
                details["value"] = value
            elif op == ord("+"):
                kind = "marker_size"
                size = finite_floats(c.take("marker_size", 4), "marker_size")[0]
                details["size"] = size
                if size < 0:
                    units = c.byte("marker_size_units")
                    if units > 4:
                        raise ProfileMismatch("Unknown marker size units")
                    details["units"] = units
            elif op == ord("}"):
                kind = "view"
                projection = c.byte("projection")
                if projection & ~0x1F:
                    raise ProfileMismatch("Unknown projection flags")
                values = finite_floats(c.take("view_values", 44), "view_values")
                if values[9] <= 0 or values[10] <= 0:
                    raise ProfileMismatch("Non-positive view field dimensions")
                for bit in (4, 8, 16):
                    if projection & bit:
                        finite_floats(c.take("view_optional", 4), "view_optional")
                raw_name = c.blob("view_name")
                name = ascii_candidate(raw_name)
                details.update(projection=projection, field_size=list(values[9:11]))
            elif op == ord("f"):
                kind = "font"
                if c.byte("font_format") != 0:
                    raise ProfileMismatch("Unimplemented font format")
                name = ascii_candidate(c.blob("font_name"))
                details["encoding"] = c.byte("font_encoding")
                c.blob("font_lookup")
                # TK_Font::Read and m_length's int declaration corroborate i32;
                # the public HTML table incorrectly calls this field a Byte.
                length = struct.unpack("<i", c.take("font_data_length", 4))[0]
                c.take("font_data", length)
                details["data_bytes"] = length
            elif op == ord("U"):
                kind = "user_options"
                length = struct.unpack("<H", c.take("options_length", 2))[0]
                if length == 65535:
                    length = c.u32("options_long_length")
                c.take("options", length)
            elif op == ord("("):
                kind = "open_segment"
                raw_name = c.blob("segment_name")
                name = ascii_candidate(raw_name)
                depth += 1
            elif op == ord(")"):
                kind = "close_segment"
                if depth == 0:
                    raise ProfileMismatch("Unbalanced close segment in suffix")
                depth -= 1
            elif op == ord("q"):
                kind = "tag_implicit"
            else:
                stopped = f"unimplemented_opcode_0x{op:02x}"
                c.position = at
                break
            records.append(
                {
                    "opcode": op,
                    "kind": kind,
                    "offset": at,
                    "length": c.position - at,
                    "name_ascii": name,
                    **details,
                }
            )
        except ProfileMismatch as exc:
            stopped = str(exc)
            c.position = at
            break
    else:
        stopped = "audit_record_limit"
    return {
        "status": "partial",
        "start": start,
        "end": c.position,
        "records": records,
        "stop_reason": stopped,
        "stop_opcode": data[c.position] if c.position < len(data) else None,
        "open_depth_at_stop": depth,
    }
