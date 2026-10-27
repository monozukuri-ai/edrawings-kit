"""Independent fixture bytes, coordinate expectations and semantics boundaries."""

import dataclasses
import gc
import json
import struct
import subprocess
import sys
import zlib

import edrawings_kit as ed
import pytest
from edrawings_kit import _core

HEADER = b";; HSF V19.10 \n"
LABEL = "寸法 10 mm 🦀"
RECTANGLE = ((0, 0, 2), (3, 0, 2), (3, 4, 2), (0, 4, 2), (0, 0, 2))
ARC = ((5, 0, 2), (0, 5, 2), (-5, 0, 2))


def points(values):
    return b"".join(struct.pack("<3f", *p) for p in values)


def encoded_text(code, raw, length_kind=255, *, modern=True):
    length = (
        bytes([length_kind])
        + struct.pack("<H" if length_kind == 254 else "<I", len(raw))
        if length_kind in (254, 255)
        else bytes([len(raw)])
    )
    return (
        b"x"
        + points(((1, 2, 2),))
        + bytes([code])
        + length
        + raw
        + (b"\0" if modern else b"")
    )


def fixture():
    options = "refname=部品,configname=標準".encode("utf-16-le")
    return (
        b"(\x06SheetA~\x14\x10\x20\x30V\x14\x04"
        + b"\x16"
        + struct.pack("<H", len(options) // 2)
        + options
        + b"L"
        + struct.pack("<i", len(RECTANGLE))
        + points(RECTANGLE)
        + b"l"
        + points(((0, 0, 2), (3, 4, 2)))
        + b"C"
        + points(ARC)
        + b"\x01"
        + points(((0, 0, 2),))
        + b"c"
        + points(ARC)
        + b"\0"
        + encoded_text(5, LABEL.encode("utf-16-le"))
        + b")q(\x06SheetB%"
        + struct.pack("<12f", 1, 0, 0, 0, 1, 0, 0, 0, 1, 10, 20, 0)
        + b"r\0\0\0\0)"
    )


@pytest.mark.parametrize("kind", ["raw", "zip", "prefixed"])
@pytest.mark.parametrize("compressed", [False, True])
def test_drawing_coordinates_unicode_provenance_and_unverified_sheets(
    kind, compressed, zip_factory, tmp_path
):
    body = fixture()
    raw = HEADER + (b"Z" + zlib.compress(body + b"z") if compressed else body) + b"\0"
    data = (
        raw
        if kind == "raw"
        else zip_factory([("eModel", raw)], prefix=kind == "prefixed")
    )
    path = tmp_path / "drawing.edrw"
    path.write_bytes(data)
    doc = ed.read_file(path)
    drawing = doc.read_drawing()
    assert doc.inspection.document_kind == "unknown"
    assert doc.inspection.stages.scene == "not_requested"
    assert drawing.summary.to_dict() == json.loads(
        _core.read_bytes(data, "{}").read_drawing().summary_json()
    )
    s = drawing.summary.scene
    a = drawing.summary.assessment
    assert s.status == "complete" and a.status == "partial"
    assert (
        a.sheet_status,
        a.view_status,
        a.dimension_status,
        a.component_status,
        a.configuration_status,
    ) == ("unsupported",) * 5
    assert [n.name for n in s.nodes] == ["/", "SheetA", "SheetB"]
    assert not s.meshes and s.units is None
    assert len(s.primitives) == 5 and len(s.primitive_instances) == 10
    assert all(p.owner_node_id == s.nodes[1].id for p in s.primitives)
    expected = (RECTANGLE, ((0, 0, 2), (3, 4, 2)), ARC, ARC, ((1, 2, 2),))
    for primitive, values in zip(s.primitives, expected, strict=True):
        buf = drawing.primitive_points(primitive.id)
        assert buf.dtype == "<f4" and buf.shape == (len(values), 3)
        assert (
            buf.data == points(values) == drawing.source_bytes(primitive.points_source)
        )
    # The diagonal is 5, the circle control points have radius 5. These numbers
    # are coordinates, not inferred length units or semantic dimensions.
    diagonal = struct.unpack("<6f", drawing.primitive_points(s.primitives[1].id).data)
    assert sum((diagonal[i + 3] - diagonal[i]) ** 2 for i in range(3)) == 25
    assert s.primitives[2].center.value == (0, 0, 2)
    assert s.primitives[3].center is None
    label = s.primitives[4].text
    assert (
        label.value == LABEL and label.encoding_code == 5 and label.status == "complete"
    )
    assert drawing.source_bytes(label.source) == LABEL.encode("utf-16-le")
    assert s.user_options[0].text.value == "refname=部品,configname=標準"
    assert s.user_options[0].node_id == s.nodes[1].id
    for i in s.primitive_instances[5:]:
        assert i.world_transform[12:15] == (10, 20, 0)
        assert i.display.colors[2].value == (16, 32, 48)
        assert i.display.visibility[2].value is True
        assert i.display.visibility[4].value is False
        assert i.display.colors[0] is None
    with pytest.raises(
        ed.UnsupportedFeatureError, match="drawing.document_semantics_unverified"
    ):
        doc.read_drawing(mode="strict")
    generic = doc.read_scene(mode="strict")
    assert generic.primitive_points(generic.summary.primitives[0].id).data == points(
        RECTANGLE
    )
    path.unlink()
    del doc, generic
    gc.collect()
    assert drawing.source_bytes(label.source) == LABEL.encode("utf-16-le")
    with pytest.raises(ed.InvalidFormatError, match="scene.unknown_primitive"):
        drawing.primitive_points("absent")
    with pytest.raises(ed.InvalidFormatError, match="hsf.invalid_source_range"):
        drawing.source_bytes(ed.HsfSpan(label.source.domain_id, 2**64 - 1, 2))
    with pytest.raises(dataclasses.FrozenInstanceError):
        a.status = "complete"


@pytest.mark.parametrize("version", ["8.05", "14.50", "19.10"])
@pytest.mark.parametrize("length_kind", [0, 254, 255])
@pytest.mark.parametrize(
    "code,encoding,text",
    [
        (0, "latin1", "café"),
        (5, "utf-16-le", LABEL),
        (6, "utf-32-le", LABEL),
        (10, "utf-8", LABEL),
    ],
)
def test_text_versions_length_forms_and_encodings(
    version, length_kind, code, encoding, text
):
    raw = text.encode(encoding)
    data = (
        f";; HSF V{version} \n".encode()
        + encoded_text(code, raw, length_kind, modern=version != "8.05")
        + b"\0"
    )
    s = ed.read(data).read_scene(mode="strict")
    value = s.summary.primitives[0].text
    assert value.value == text and value.encoding_code == code
    assert s.source_bytes(value.source) == raw


def test_ascii_and_unknown_encoding_have_separate_statuses():
    for raw in [b"abc", b"\xff"]:
        data = HEADER + b"T" + points(((0, 0, 0),)) + bytes([len(raw)]) + raw + b"\0\0"
        doc = ed.read(data)
        s = doc.read_scene()
        p = s.summary.primitives[0]
        assert p.text.value == ("abc" if raw.isascii() else None)
        assert s.source_bytes(p.text.source) == raw
        assert len(s.summary.primitive_instances) == 1
        if not raw.isascii():
            assert s.summary.status == "partial"
            with pytest.raises(ed.UnsupportedFeatureError, match="hsf.text_encoding"):
                doc.read_scene(mode="strict")
    doc = ed.read(HEADER + encoded_text(2, b"\x82\xa0") + b"\0")
    assert doc.read_drawing().summary.scene.status == "partial"
    assert doc.read_scene().summary.primitives[0].text.encoding == "unsupported"


@pytest.mark.parametrize(
    "code,raw",
    [
        (5, b"\0\xd8"),
        (5, b"x"),
        (6, b"\0\xd8\0\0"),
        (6, b"\0\0\x11\0"),
        (10, b"\xc0\x80"),
        (10, b"\xed\xa0\x80"),
        (10, b"\xf4\x90\x80\x80"),
        (10, b"\xe5\xaf"),
        (10, b"\x80"),
    ],
)
@pytest.mark.parametrize("mode", ["partial", "strict"])
def test_invalid_unicode_is_not_lossy_or_partial(code, raw, mode):
    with pytest.raises(ed.InvalidFormatError, match="hsf.invalid_text_encoding") as err:
        ed.read(HEADER + encoded_text(code, raw) + b"\0").read_drawing(mode=mode)
    assert err.value.diagnostic.entry_id == "raw:0"
    assert err.value.diagnostic.domain_id == "raw:0/hsf:0"


@pytest.mark.parametrize("length,form", [(0, 0), (253, 0), (254, 254), (65536, 255)])
def test_utf8_byte_lengths_and_exact_output_budget(length, form):
    # Use multibyte text and byte counts, not Unicode character counts.
    raw = "寸".encode() * (length // 3) + b"a" * (length % 3)
    data = HEADER + encoded_text(10, raw, form) + b"\0"
    parsed = ed.read(data).read_scene(mode="strict")
    t = parsed.summary.primitives[0].text
    assert t.encoding == "utf_8" and t.value == raw.decode()
    assert t.source.length == length and parsed.source_bytes(t.source) == raw
    limit = parsed.summary.usage.output_bytes
    bounded = dataclasses.replace(ed.Limits(), max_output_bytes=limit)
    assert (
        ed.read(data, limits=bounded).read_scene(mode="strict").summary
        == parsed.summary
    )
    with pytest.raises(ed.LimitExceededError):
        ed.read(
            data, limits=dataclasses.replace(bounded, max_output_bytes=limit - 1)
        ).read_scene(mode="strict")


def test_combined_resource_budget_and_definition_limits(zip_factory):
    body = fixture() + b"z"
    raw = HEADER + b"Z" + zlib.compress(body) + b"\0"
    data = zip_factory([("eModel", raw)])
    d = ed.read(data).read_drawing()
    usage = d.summary.scene.usage
    assert usage.expanded_bytes == len(raw) + len(body)
    limits = dataclasses.replace(
        ed.Limits(),
        max_output_bytes=usage.output_bytes,
        max_expanded_bytes=usage.expanded_bytes,
    )
    assert ed.read(data, limits=limits).read_drawing().summary.scene.usage == usage
    for field, value in [
        ("max_output_bytes", usage.output_bytes - 1),
        ("max_expanded_bytes", usage.expanded_bytes - 1),
        ("max_scene_primitives", 4),
        ("max_scene_instances", 9),
        ("max_hsf_vertices", 14),
        ("max_hsf_string_bytes", 4),
    ]:
        with pytest.raises(ed.LimitExceededError):
            ed.read(
                data, limits=dataclasses.replace(limits, **{field: value})
            ).read_drawing()


def test_cli_entry_selection_and_no_resynchronization(zip_factory, tmp_path):
    raw = HEADER + fixture() + b"\0"
    doc = ed.read(zip_factory([("eModel", raw), ("eModel", raw)]))
    with pytest.raises(ed.UnsupportedFeatureError, match="hsf.ambiguous_candidates"):
        doc.read_drawing()
    a, b = (doc.read_drawing(f"entry:{i}").summary.scene for i in range(2))
    assert a.primitives[0].id != b.primitives[0].id
    assert a.user_options[0].node_id != b.user_options[0].node_id
    with pytest.raises(ValueError, match="mode"):
        doc.read_drawing("entry:0", mode="oops")
    path = tmp_path / "drawing.hsf"
    path.write_bytes(raw)
    args = [sys.executable, "-m", "edrawings_kit", "drawing", str(path)]
    run = subprocess.run(args, check=True, capture_output=True, encoding="utf-8")
    assert (
        json.loads(run.stdout)
        == ed.read(raw, read_metadata=False).read_drawing().summary.to_dict()
    )
    run = subprocess.run(
        args + ["--mode", "strict"], capture_output=True, encoding="utf-8"
    )
    assert run.returncode == 2
    assert (
        json.loads(run.stderr)["error"]["code"]
        == "drawing.document_semantics_unverified"
    )
    for prefix in [b"[", b"i", b"o", b"\xfe"]:
        d = ed.read(HEADER + prefix + fixture() + b"\0").read_drawing()
        assert d.summary.scene.status == "partial" and not d.summary.scene.primitives
        assert d.summary.scene.hsf.unparsed[0].offset == len(HEADER)
