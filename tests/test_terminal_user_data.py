"""Independent fixtures for the explicit, opaque terminal BE envelope."""

import gc
import io
import json
import struct
import subprocess
import sys
import zipfile
import zlib

import edrawings_kit as ed
import pytest
from test_user_data_audit import sample

PROFILE = "edrawings_be_envelope_v1"
FIRST = "edrawings_first_be_v2"
PAIRS = [
    ("8.05", 22),
    ("14.50", 39),
    ("19.10", 45),
    ("19.10", 46),
    ("19.10", 48),
    ("19.10", 51),
]


def terminal(revision=46):
    return (
        b"["
        + struct.pack("<IBI", 9, 190, revision)
        + bytes(8 if revision == 22 else 12)
        + b"]"
    )


def first(revision=46):
    return sample(revision, modern=revision != 22)


def packed(body, version="19.10", parent=b"\0", prefix=None):
    if prefix is None:
        prefix = b"I\4\0\0\0B\0" + bytes(24)
    return (
        f";; HSF V{version} \n".encode() + prefix + b"Z" + zlib.compress(body) + parent
    )


def make(revision=46, version="19.10", middle=b"h\0\1", suffix=None, parent=b"\0"):
    return packed(
        first(revision)
        + middle
        + (terminal(revision) + b"z" if suffix is None else suffix),
        version,
        parent,
    )


@pytest.mark.parametrize("version,revision", PAIRS)
@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed"])
def test_closed_terminal_envelope_complete_coverage_stays_partial(
    version, revision, wrapper
):
    body = first(revision) + b"h\0\1" + terminal(revision) + b"z"
    data = packed(body, version)
    if wrapper != "raw":
        b = io.BytesIO()
        with zipfile.ZipFile(b, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("eModel", data)
        data = b.getvalue()
        if wrapper == "prefixed":
            from conftest import PREFIX

            data = PREFIX + data
    doc = ed.read(data)
    old = doc.parse_hsf(user_data_profile=FIRST)
    h = doc.parse_hsf(user_data_profile=PROFILE)
    assert old.summary.records == h.summary.records[:-3]
    assert not h.summary.unparsed and all(
        d.byte_len == d.parsed_bytes for d in h.summary.domains
    )
    assert h.summary.stages.hsf_syntax == "partial"
    assert all(
        d.code == "hsf.experimental_user_data" and d.severity == "warning"
        for d in h.summary.diagnostics
    )
    r, stop, end = h.summary.records[-3:]
    assert [r.opcode, stop.opcode, end.opcode] == [91, 122, 0]
    u = r.user_data
    assert u.profile == f"edrawings-terminal-be-v1-hsf-{version}-revision-{revision}"
    assert (
        u.evidence_level == "empirical_corpus_layout" and not u.native_reader_verified
    )
    assert u.declared_length == 9 and u.computed_payload_length == (
        13 if revision == 22 else 17
    )
    assert h.source_bytes(r.source) == terminal(revision)
    assert r.source.offset == len(first(revision)) + 3
    offset = r.source.offset
    for f in u.fields:
        assert f.source.offset == offset and f.source.domain_id == r.source.domain_id
        offset += f.source.length
    assert offset == stop.source.offset
    assert [f.label for f in u.fields] == [
        "start",
        "declared_length",
        "private_identifier",
        "internal_revision",
        "opaque_zero_tail",
        "stop",
    ]
    assert h.source_bytes(u.fields[3].source) == struct.pack("<I", revision)
    assert h.source_bytes(u.fields[4].source) == bytes(8 if revision == 22 else 12)
    scene = doc.read_scene(user_data_profile=PROFILE)
    assert scene.summary.processed_records == len(h.summary.records)
    assert len(scene.summary.opaque_user_data) == 2
    assert scene.summary.diagnostics[-1].code == "hsf.terminal_user_data_inventory"
    assert (
        scene.summary.status == "partial"
        and scene.summary.placement_status == "unsupported"
    )
    assert not scene.summary.instances and not scene.summary.primitive_instances
    assert (
        doc.read_drawing(user_data_profile=PROFILE).summary.assessment.status
        == "partial"
    )
    assert doc.parse_hsf().summary.domains[1].parsed_bytes == 0
    for method in [doc.parse_hsf, doc.read_scene, doc.read_drawing]:
        with pytest.raises(ed.UnsupportedFeatureError) as err:
            method(user_data_profile=PROFILE, mode="strict")
        assert err.value.diagnostic.code == "hsf.experimental_user_data"
    del doc
    gc.collect()
    assert h.source_bytes(r.source) == terminal(revision)


@pytest.mark.parametrize("version,revision", PAIRS)
def test_every_byte_mutation_and_truncation_stops_without_resync(version, revision):
    tail = terminal(revision) + b"z"
    offset = len(first(revision)) + 3
    candidates = [tail[:end] for end in range(1, len(tail))]
    for at in range(1, len(tail)):
        bad = bytearray(tail)
        bad[at] ^= 0x01
        candidates.append(bytes(bad))
    candidates += [tail + b"z", tail + b"\0", tail[:-2] + b"\0]z", tail + b"]z"]
    for suffix in candidates:
        h = ed.read(make(revision, version, suffix=suffix)).parse_hsf(
            user_data_profile=PROFILE
        )
        assert h.summary.domains[1].parsed_bytes == offset
        assert len([r for r in h.summary.records if r.user_data]) == 1
        assert h.summary.diagnostics[-1].classification == "unsupported"
        assert h.summary.diagnostics[-1].byte_range.offset == offset


@pytest.mark.parametrize(
    "middle,parent",
    [
        (b"h\0", b"\0"),  # no Pause
        (b"h\0\1;comment\n", b"\0"),
        (b"h\0(\1a\1", b"\0"),  # open scope despite the Pause
        (b"h\0\1", b"h\0\0"),  # valid outer commands, outside this terminal profile
        (b"h\0\1", b"\0\0"),
        (b"h\0\1", b""),
    ],
)
def test_context_must_be_closed_paused_and_at_both_ends(middle, parent):
    h = ed.read(make(middle=middle, parent=parent)).parse_hsf(user_data_profile=PROFILE)
    assert len([r for r in h.summary.records if r.user_data]) == 1
    assert h.summary.domains[1].parsed_bytes == len(first()) + len(middle)
    assert h.summary.diagnostics[-1].code == "hsf.unsupported_user_data"


@pytest.mark.parametrize("revision", [22, 39, 45, 47, 48])
def test_terminal_revision_must_equal_accepted_first_header(revision):
    h = ed.read(make(suffix=terminal(revision) + b"z")).parse_hsf(
        user_data_profile=PROFILE
    )
    assert len([r for r in h.summary.records if r.user_data]) == 1


def test_raw_domain_second_domain_and_missing_first_header_do_not_match():
    body = b"h\0\1" + terminal() + b"z"
    raw = b";; HSF V19.10 \n" + body[:-1] + b"\0"
    no_first = packed(body)
    second = packed(first() + b"h\0z", parent=b"Z" + zlib.compress(body) + b"\0")
    for data in (raw, no_first, second):
        h = ed.read(data).parse_hsf(user_data_profile=PROFILE)
        assert not any(
            r.user_data and r.user_data.profile.startswith("edrawings-terminal")
            for r in h.summary.records
        )
        assert h.summary.diagnostics[-1].code == "hsf.unsupported_user_data"


def test_second_lookalike_in_middle_is_not_skipped_to_real_terminal():
    t = terminal()
    h = ed.read(make(suffix=t + b"\1" + t + b"z")).parse_hsf(user_data_profile=PROFILE)
    assert h.summary.domains[1].parsed_bytes == len(first()) + 3


def test_record_and_metadata_limits_still_apply_before_terminal_inventory():
    data = make()
    count = len(ed.read(data).parse_hsf(user_data_profile=PROFILE).summary.records)
    with pytest.raises(ed.LimitExceededError) as err:
        ed.read(data, limits=ed.Limits(max_hsf_records=count - 1)).parse_hsf(
            user_data_profile=PROFILE
        )
    assert err.value.diagnostic.code == "hsf.limit_records"
    old = ed.read(data).parse_hsf(user_data_profile=FIRST)
    with pytest.raises(ed.LimitExceededError) as err:
        ed.read(
            data, limits=ed.Limits(max_output_bytes=old.summary.usage.output_bytes)
        ).parse_hsf(user_data_profile=PROFILE)
    assert err.value.diagnostic.code == "budget.output"


def test_inventory_keeps_local_geometry_and_semantic_stops():
    line = b"l" + struct.pack("<6f", 1, 2, 3, 4, 5, 6)
    scene = ed.read(make(middle=b"h\0(\1a" + line + b")\1")).read_scene(
        user_data_profile=PROFILE
    )
    assert (
        len(scene.summary.primitives) == 1 and len(scene.summary.opaque_user_data) == 2
    )
    assert scene.primitive_points(scene.summary.primitives[0].id).data == line[1:]
    assert not scene.summary.primitive_instances
    # A valid syntax path with unresolved scene semantics must still stop early.
    s = ed.read(make(middle=b"h\0(\2?a)\1")).read_scene(user_data_profile=PROFILE)
    assert not s.summary.hsf.unparsed and len(s.summary.opaque_user_data) == 1
    assert s.summary.diagnostics[-1].code == "hsf.segment_path"


@pytest.mark.parametrize("command", ["hsf", "scene", "drawing"])
def test_cli_and_python_match(tmp_path, command):
    path = tmp_path / "terminal.hsf"
    path.write_bytes(make())
    run = subprocess.run(
        [
            sys.executable,
            "-m",
            "edrawings_kit",
            command,
            str(path),
            "--user-data-profile",
            PROFILE,
        ],
        check=True,
        capture_output=True,
        encoding="utf-8",
    )
    method = {"hsf": "parse_hsf", "scene": "read_scene", "drawing": "read_drawing"}[
        command
    ]
    assert (
        json.loads(run.stdout)
        == getattr(ed.read_file(path, read_metadata=False), method)(
            user_data_profile=PROFILE
        ).summary.to_dict()
    )
