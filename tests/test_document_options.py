"""Stored application assignments: grammar, wire provenance and uncertainty."""

import dataclasses
import gc
import json
import struct
import zlib

import edrawings_kit as ed
import pytest
from edrawings_kit import _core

HEADER = b";; HSF V19.10 \n"


def options(text, encoding="ascii"):
    raw = text.encode(encoding)
    if encoding == "ascii":
        return b"U" + struct.pack("<H", len(raw)) + raw
    assert encoding == "utf-16-le"
    return b"\x16" + struct.pack("<H", len(raw) // 2) + raw


@pytest.mark.parametrize("encoding", ["ascii", "utf-16-le"])
@pytest.mark.parametrize("quote", ["'", '"', "`"])
@pytest.mark.parametrize("kind", ["raw", "zip", "prefixed"])
def test_quoted_commas_equals_case_empty_and_source(encoding, quote, kind, zip_factory):
    label = "Sheet,A=B" if encoding == "ascii" else "図面,A=寸法 🦀"
    text = (
        f" NAME = {quote}{label}{quote}, "
        "templatewidth=0.297, empty='', flag, no Hidden "
    )
    body = b"(\x06sheet0" + options(text, encoding) + b")z"
    raw = HEADER + b"Z" + zlib.compress(body) + b"\0"
    data = (
        raw
        if kind == "raw"
        else zip_factory([("eModel", raw)], prefix=kind == "prefixed")
    )
    doc = ed.read(data)
    drawing = doc.read_drawing()
    assert drawing.summary.to_dict() == json.loads(
        _core.read_bytes(data, "{}").read_drawing().summary_json()
    )
    (record,) = drawing.summary.user_option_records
    assert record.node_id == drawing.summary.scene.nodes[1].id
    assert record.parsing_status == "complete" and record.reason is None
    assert [(a.name, a.value, a.value_kind) for a in record.assignments] == [
        ("name", label, "explicit"),
        ("templatewidth", "0.297", "explicit"),
        ("empty", "", "explicit"),
        ("flag", "on", "implicit_on"),
        ("hidden", "off", "implicit_off"),
    ]
    name, width, empty, flag, hidden = record.assignments
    assert drawing.source_bytes(name.name_source) == b"NAME".decode().encode(encoding)
    assert drawing.source_bytes(name.value_source) == label.encode(encoding)
    assert drawing.source_bytes(name.value_token_source) == (
        quote + label + quote
    ).encode(encoding)
    assert drawing.source_bytes(width.value_source) == "0.297".encode(encoding)
    assert drawing.source_bytes(empty.value_source) == b""
    assert drawing.source_bytes(hidden.source) == "no Hidden".encode(encoding)
    assert flag.value_source is None and hidden.value_token_source is None
    assert drawing.summary.assessment.sheet_status == "unsupported"
    assert drawing.summary.scene.units is None
    del doc
    gc.collect()
    assert drawing.source_bytes(record.source) == text.encode(encoding)


@pytest.mark.parametrize(
    "text",
    [
        "a=1,b=`unterminated",
        "a=1,b='q'junk",
        "a=1,",
        "a=1,,b=2",
        "=empty",
        "a=1,2_va",
        "a=D=40_M6",
        "a=not'quoted",
        "a=1,名=値",
        "🦀",
        "名x",
        "a=\x00",
        "a=1,no  hidden",
        "a=1,no ",
    ],
)
def test_unsupported_record_is_atomic_and_raw_is_available(text):
    data = HEADER + options(text, "utf-16-le") + b"\0"
    d = ed.read(data).read_drawing()
    (record,) = d.summary.user_option_records
    assert record.parsing_status == "unsupported"
    assert not record.assignments
    assert drawing_raw(d, record) == text.encode("utf-16-le")
    assert d.summary.scene.status == "complete"
    with pytest.raises(
        ed.UnsupportedFeatureError, match="document_semantics_unverified"
    ):
        ed.read(data).read_drawing(mode="strict")


def drawing_raw(drawing, record):
    return drawing.source_bytes(record.source)


def test_events_are_not_silently_collapsed_or_inherited():
    body = (
        options("name=Root,NAME=LastRoot")
        + b"(\x05child"
        + options("name=Child")
        + b")"
        + options("name=FinalRoot")
    )
    d = ed.read(HEADER + body + b"\0").read_drawing()
    records = d.summary.user_option_records
    assert [[a.value for a in r.assignments] for r in records] == [
        ["Root", "LastRoot"],
        ["Child"],
        ["FinalRoot"],
    ]
    assert records[0].node_id == records[2].node_id != records[1].node_id
    assert len({r.source_record_id for r in records}) == 3


def test_unknown_encoding_empty_records_and_bare_windows_paths():
    data = HEADER + options("") + options(" \t ") + b"U\x01\x00\xff" + b"\0"
    d = ed.read(data).read_drawing()
    assert [r.parsing_status for r in d.summary.user_option_records] == [
        "complete",
        "complete",
        "unsupported",
    ]
    assert all(not r.assignments for r in d.summary.user_option_records)
    text = r"path=C:\cad\part.sldprt,refname=Part-1,config name=Default"
    (record,) = (
        ed.read(HEADER + options(text) + b"\0")
        .read_drawing()
        .summary.user_option_records
    )
    assert record.parsing_status == "complete"
    assert record.assignments[0].value == r"C:\cad\part.sldprt"


def test_shared_budget_includes_parsed_assignments():
    data = HEADER + options("name=Sheet1,templatewidth=0.297") + b"\0"
    d = ed.read(data).read_drawing()
    used = d.summary.scene.usage.output_bytes
    exact = dataclasses.replace(ed.Limits(), max_output_bytes=used)
    assert (
        ed.read(data, limits=exact).read_drawing().summary.scene.usage.output_bytes
        == used
    )
    with pytest.raises(ed.LimitExceededError, match="budget.output"):
        ed.read(
            data, limits=dataclasses.replace(exact, max_output_bytes=used - 1)
        ).read_drawing()
    data = HEADER + options(",".join("a=1" for _ in range(4097))) + b"\0"
    with pytest.raises(ed.LimitExceededError, match="drawing_user_options"):
        ed.read(data).read_drawing()
