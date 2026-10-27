import dataclasses
import hashlib
import importlib.metadata
import json
import struct
import subprocess
import sys
import zipfile
from pathlib import Path

import edrawings_kit as ed
import pytest
from conftest import HSF, PREFIX
from edrawings_kit import _core
from packaging.version import Version


@pytest.mark.parametrize("kind", ["raw", "zip", "prefixed"])
def test_three_containers_and_typed_contract(kind, zip_factory, tmp_path):
    data = HSF if kind == "raw" else zip_factory(prefix=kind == "prefixed")
    path = tmp_path / "drawing.edrw"
    path.write_bytes(data)
    info = ed.inspect(data)
    assert info.file_sha256 == hashlib.sha256(data).hexdigest()
    assert info.document_kind == "unknown"
    assert info.stages.hsf_syntax == "not_requested"
    assert info.to_dict() == json.loads(_core.inspect_bytes(data, "{}"))
    assert ed.probe_file(path) == ed.probe(data)
    assert ed.inspect_file(path).filename_hint == str(path)
    doc = ed.read_file(path)
    path.write_bytes(b"source changed")
    extracted = doc.extract(info.hsf_candidates[0])
    assert extracted.data == HSF
    header = doc.inspect_hsf()
    assert header.header.version == "19.10"
    assert header.syntax_status == "not_requested"
    assert header.unparsed_range.offset == 15
    assert header.unparsed_range.length == len(HSF) - 15
    assert header.source.decoded_range.offset == 0
    assert header.source.payload_sha256 == hashlib.sha256(HSF).hexdigest()
    assert header.source.container_range.offset == (
        128 if kind == "prefixed" else 36 if kind == "zip" else 0
    )
    assert ed.read(data).verify_all()[0].sha256 == extracted.info.sha256
    with pytest.raises(dataclasses.FrozenInstanceError):
        info.document_kind = "part"


@pytest.mark.parametrize("method", [zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED])
@pytest.mark.parametrize("prefix", [False, True])
@pytest.mark.parametrize("descriptor", [False, True])
def test_compression_and_data_descriptors(zip_factory, method, prefix, descriptor):
    data = zip_factory(
        [("eModel", HSF), ("empty", b""), ("unknown", bytes(range(256)))],
        method=method,
        prefix=prefix,
        descriptor=descriptor,
    )
    doc = ed.read(data, verify_all=True)
    assert [e.crc_status for e in doc.inspection.entries] == ["verified"] * 3
    assert doc.extract("entry:2").data == bytes(range(256))


def test_unknown_duplicate_and_untrusted_names(zip_factory):
    doc = ed.read(
        zip_factory([("eModel", HSF), ("eModel", HSF), ("../../x", b"secret")])
    )
    assert [e.id for e in doc.inspection.entries] == ["entry:0", "entry:1", "entry:2"]
    with pytest.raises(ed.UnsupportedFeatureError) as exc:
        doc.inspect_hsf()
    assert exc.value.code == "hsf.ambiguous_candidates"
    assert doc.inspect_hsf("entry:1").header.major == 19
    assert doc.extract("entry:2").data == b"secret"
    with pytest.raises(ed.InvalidFormatError, match="entry.not_found"):
        doc.extract("eModel")


def test_crc_checks_are_lazy_and_structured(zip_factory):
    data = bytearray(zip_factory(method=zipfile.ZIP_STORED))
    data[36] ^= 1
    doc = ed.read(bytes(data))
    assert doc.inspection.entries[0].crc_status == "not_checked"
    with pytest.raises(ed.InvalidFormatError) as exc:
        doc.extract("entry:0")
    assert exc.value.code == "zip.crc_mismatch"
    assert exc.value.diagnostic.entry_id == "entry:0"
    assert exc.value.stage == "extraction"
    with pytest.raises(ed.InvalidFormatError):
        ed.read(bytes(data), verify_all=True)


def test_limits_and_cumulative_budget(zip_factory):
    data = zip_factory([("one", b"a" * 60), ("two", b"b" * 60)])
    doc = ed.read(data, limits=ed.Limits(max_expanded_bytes=100))
    assert len(doc.extract("entry:0").data) == 60
    assert len(doc.extract("entry:1").data) == 60
    with pytest.raises(ed.LimitExceededError, match="budget.expanded"):
        doc.verify_all()
    for limits in [
        ed.Limits(max_file_bytes=1),
        ed.Limits(max_entries=0),
        ed.Limits(max_output_bytes=0),
    ]:
        with pytest.raises(ed.LimitExceededError):
            ed.read(data, limits=limits)
    for limits in [ed.Limits(max_entry_bytes=10), ed.Limits(max_compression_ratio=1)]:
        doc = ed.read(data, limits=limits)
        with pytest.raises(ed.LimitExceededError):
            doc.extract("entry:0")
    with pytest.raises(ValueError):
        ed.Limits(max_file_bytes=-1)
    with pytest.raises(ValueError):
        ed.Limits(max_file_bytes=True)


@pytest.mark.parametrize(
    "body", [b"<a><b/></a>", "<scene><部品 name='部品'/></scene>".encode()]
)
def test_metadata_is_structural_only(zip_factory, body):
    doc = ed.read(zip_factory([("scene.xml", body)]))
    assert doc.metadata[0].elements == 2
    assert doc.metadata[0].semantic_status == "not_requested"
    assert doc.inspection.stages.metadata == "partial"
    assert doc.extract("entry:0").data == body


@pytest.mark.parametrize(
    "body",
    [
        b"<1/>",
        b"<a>\x00</a>",
        b'<a x="a<b"/>',
        b'<?xml version="1.0"?><?xml version="1.0"?><a/>',
        b"<a></b>",
        b"<a>",
        b"<a/><b/>",
        b"outside<a/>",
        b"<a x='1' x='2'/>",
        b"<a>&unresolved;</a>",
        b"<!-- bad -- comment --><a/>",
    ],
)
def test_invalid_xml_is_not_silently_accepted(zip_factory, body):
    data = zip_factory([("scene.xml", body)])
    with pytest.raises(ed.InvalidFormatError):
        ed.read(data)
    assert ed.read(data, read_metadata=False).extract("entry:0").data == body


def test_dtd_and_xml_limits(zip_factory):
    data = zip_factory(
        [("scene.xml", b"<!DOCTYPE a SYSTEM 'https://example.invalid'><a/>")]
    )
    with pytest.raises(ed.UnsupportedFeatureError, match="xml.dtd"):
        ed.read(data)
    data = zip_factory([("scene.xml", b"<a><b/></a>")])
    for limits in [
        ed.Limits(max_xml_bytes=1),
        ed.Limits(max_xml_depth=1),
        ed.Limits(max_xml_elements=1),
    ]:
        with pytest.raises(ed.LimitExceededError):
            ed.read(data, limits=limits)


def test_invalid_hsf_header_and_unknown_inputs():
    assert ed.probe(b"not a CAD file").input_kind == "unknown"
    with pytest.raises(ed.UnsupportedFeatureError):
        ed.inspect(b"not a CAD file")
    assert ed.probe(b";; HSF V19.10").diagnostics[0].code == "hsf.invalid_header"
    with pytest.raises(ed.InvalidFormatError):
        ed.read(b";; HSF V19.10")
    for data in [b";; HSF V19.1\n", b";; HSF V19.10garbage\n"]:
        with pytest.raises(ed.InvalidFormatError):
            ed.inspect(data)
    with pytest.raises(TypeError):
        ed.read("path.eprt")
    with pytest.raises(TypeError):
        ed.read(bytearray(HSF))


def test_io_errors_remain_os_errors(tmp_path):
    with pytest.raises(FileNotFoundError):
        ed.read_file(tmp_path / "missing")


def test_zip_corruption_offsets_overlaps_and_unsupported(zip_factory):
    good = zip_factory(method=zipfile.ZIP_STORED)
    central = good.index(b"PK\x01\x02")
    for at in [14, 18, 22, 30]:
        data = bytearray(good)
        data[at] ^= 1
        with pytest.raises(ed.InvalidFormatError):
            ed.inspect(bytes(data))
    data = bytearray(good)
    struct.pack_into("<I", data, central + 42, len(good) + 100)
    with pytest.raises(ed.InvalidFormatError):
        ed.inspect(bytes(data))
    data = bytearray(good)
    struct.pack_into("<H", data, 8, 99)
    struct.pack_into("<H", data, central + 10, 99)
    doc = ed.read(bytes(data))
    assert doc.inspection.entries[0].extraction_status == "unsupported"
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.extract("entry:0")
    data = bytearray(good)
    struct.pack_into("<H", data, 6, 1)
    struct.pack_into("<H", data, central + 8, 1)
    with pytest.raises(ed.UnsupportedFeatureError):
        ed.read(bytes(data)).extract("entry:0")
    for at in [central + 20, len(good) - 22 + 16]:
        data = bytearray(good)
        struct.pack_into("<I", data, at, 0xFFFFFFFF)
        with pytest.raises(ed.UnsupportedFeatureError, match="zip.zip64"):
            ed.inspect(bytes(data))


def test_absolute_offset_prefixed_archive_and_comment(zip_factory):
    data = bytearray(zip_factory(prefix=True))
    central = data.index(b"PK\x01\x02")
    end = len(data) - 22
    struct.pack_into("<I", data, central + 42, len(PREFIX))
    struct.pack_into("<I", data, end + 16, central)
    comment = b"comment PK\x05\x06 is not an end record"
    struct.pack_into("<H", data, end + 20, len(comment))
    data.extend(comment)
    doc = ed.read(bytes(data))
    assert doc.inspection.zip_offset_base == 0
    assert doc.extract("entry:0").data == HSF


def test_truncations_and_mutated_declared_inflated_size(zip_factory):
    data = zip_factory()
    for length in range(len(data)):
        with pytest.raises(ed.EdrawingsError):
            ed.inspect(data[:length])
    for claimed in [1, len(HSF) + 10]:
        corrupt = bytearray(data)
        central = data.index(b"PK\x01\x02")
        struct.pack_into("<I", corrupt, 22, claimed)
        struct.pack_into("<I", corrupt, central + 24, claimed)
        with pytest.raises(ed.InvalidFormatError, match="zip.invalid_size"):
            ed.read(bytes(corrupt)).extract("entry:0")


def test_cli_explicit_output_and_no_overwrite(zip_factory, tmp_path):
    source = tmp_path / "input.eprt"
    source.write_bytes(zip_factory())
    output = tmp_path / "out.hsf"
    base = [sys.executable, "-m", "edrawings_kit"]
    run = subprocess.run(
        [*base, "inspect", str(source)],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(run.stdout)["input_kind"] == "zip"
    command = [
        *base,
        "extract",
        str(source),
        "--entry",
        "entry:0",
        "--output",
        str(output),
    ]
    subprocess.run(command, check=True, capture_output=True)
    assert output.read_bytes() == HSF
    run = subprocess.run(command, capture_output=True, encoding="utf-8")
    assert run.returncode == 2
    assert json.loads(run.stderr)["error"]["code"] == "io.error"
    assert output.read_bytes() == HSF
    run = subprocess.run(
        [*base, "hsf-header", str(source)],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    assert json.loads(run.stdout)["syntax_status"] == "not_requested"


def test_build_information_and_backend_fingerprint():
    info = ed.build_info()
    assert Version(info.version) == Version(importlib.metadata.version("edrawings-kit"))
    assert info.hsf_version == "0.1.0-alpha.1"
    assert "hsf_header" in info.capabilities
    assert "scene" in info.capabilities
    lock = Path(__file__).resolve().parents[1] / "hsf-backend.lock.json"
    backend = json.loads(lock.read_text())
    assert info.hsf_source_sha256 == backend["source_sha256"]
    assert info.contract_version == backend["contract_version"] == 33
    assert info.hsf_syntax_versions == ("8.05", "14.50", "19.10")
    assert ord("Z") in info.hsf_syntax_opcodes
    assert ord("S") in info.hsf_syntax_opcodes
    assert "uncompressed_shell" in info.hsf_scene_features
