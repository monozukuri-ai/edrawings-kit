"""Wire boundaries, source contracts and conservative scene handling."""

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

H = b"H\x04\0\x04\0\x01"
F = b"F\x07\x07\x03abc" + struct.pack("<fBfB", 1, 0, 0.1, 5)
COLOR = b'"\x9f\x70\x23\0\xe6\xe6\xe6\0\x7f\x7f\x7f' + struct.pack("<f", 15)
RGB = b"~\x81\x80\x80\x01\x01\x02\x03"
NULL = b"S\x96\x02\0\0"
WEIGHT = b"=" + struct.pack("<fB", -2, 4)


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed", "compressed"])
def test_new_layouts_and_source_namespaces(wrapper):
    body = H + F + COLOR + RGB + WEIGHT + NULL + b"q"
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    if wrapper in ("zip", "prefixed"):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as z:
            z.writestr("eModel", data)
        data = stream.getvalue()
        if wrapper == "prefixed":
            from conftest import PREFIX

            data = PREFIX + data
    doc = ed.read(data)
    h = doc.parse_hsf(mode="strict")
    records = {r.kind: r for r in h.summary.records}
    for name, wire in (("heuristics", H), ("text_font", F), ("color", COLOR)):
        r = records[name]
        assert isinstance(r.rendering, ed.RenderingLayout)
        assert all(isinstance(f, ed.OperandField) for f in r.rendering.fields)
        assert h.source_bytes(r.source) == wire
    font = records["text_font"].rendering
    assert font.mask == font.value == 7
    assert h.source_bytes(font.fields[0].source) == b"abc"
    assert h.source_bytes(font.fields[-1].source) == bytes([5])
    color = records["color"].rendering
    assert color.mask == 0x709F and color.value == 0x23
    assert [f.encoding for f in color.fields] == ["rgb8", "rgb8", "f32_le"]
    assert records["shell"].shell.null is True
    assert records["line_weight"].line_weight.units == 4
    s = doc.read_scene()
    assert s.summary.processed_records == len(h.summary.records)
    assert len(s.summary.rendering_options) == 3
    assert len(s.summary.null_shells) == 1
    assert isinstance(s.summary.null_shells[0], ed.NullShell)
    assert s.source_bytes(s.summary.null_shells[0].source) == NULL
    assert all(
        x.interpretation_status == "unsupported" for x in s.summary.rendering_options
    )
    assert not s.summary.meshes and not s.summary.instances
    assert s.summary.placement_status == "unsupported"
    with pytest.raises(ed.UnsupportedFeatureError) as e:
        doc.read_scene(mode="strict")
    assert e.value.diagnostic.code == "hsf.rendering_semantics"


def test_implicit_parents_sources_depth_and_close():
    body = b"(\x06/a/b/c" + RGB + WEIGHT + b"l" + POINTS + b")l" + POINTS + b"\0"
    s = ed.read(raw(body)).read_scene(mode="strict")
    nodes = s.summary.nodes
    assert [n.implicit for n in nodes] == [False, True, True, False]
    assert nodes[1].name_source is None and nodes[1].source == nodes[3].source
    first, second = s.summary.primitive_instances
    assert first.path == tuple(n.id for n in nodes)
    assert second.node_id == nodes[0].id
    assert first.display.colors[24].value == (1, 2, 3)
    assert len(first.display.colors) == 32
    assert first.display.line_weight.value == ed.MarkerSize(2, "pixels")
    assert second.display.line_weight is None
    for limits in (ed.Limits(max_scene_depth=3), ed.Limits(max_scene_nodes=3)):
        with pytest.raises(ed.LimitExceededError):
            ed.read(raw(body), limits=limits).read_scene()


@pytest.mark.parametrize("record", [H, F, COLOR, RGB, NULL, WEIGHT])
def test_every_known_operand_truncation_is_invalid(record):
    for cut in range(len(record)):
        with pytest.raises(ed.InvalidFormatError):
            ed.read(raw(record[:cut])).parse_hsf()


@pytest.mark.parametrize(
    "record",
    [
        b"H\0\x80\0\x80\0\0\0\0",
        b"F\x80\0\x80\0\0\x80\0\0",
        b'"\x01\x80\x04',
        b"~\x80\x80\x80\x80",
    ],
)
def test_unknown_flags_do_not_scan_for_following_handedness(record):
    doc = ed.read(raw(record + b"h\x01\0"))
    h = doc.parse_hsf()
    assert not h.summary.records
    assert h.source_bytes(h.summary.unparsed[0]) == record + b"h\x01\0"
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.parse_hsf(mode="strict")


def test_long_diffuse_expression_and_invalid_float():
    body = b'"\x01\x01\xff' + struct.pack("<i", 300) + b"x" * 300 + b"\0"
    h = ed.read(raw(body)).parse_hsf(mode="strict")
    f = h.summary.records[0].rendering.fields[0]
    assert h.source_bytes(f.source) == b"x" * 300 and f.encoding == "unspecified_text"
    with pytest.raises(ed.LimitExceededError):
        ed.read(raw(body), limits=ed.Limits(max_hsf_string_bytes=299)).parse_hsf()
    with pytest.raises(ed.InvalidFormatError):
        ed.read(raw(b'"\x01\x20' + struct.pack("<f", float("inf")) + b"\0")).parse_hsf()


def test_user_data_inventory_and_default_profile_are_preserved():
    body = b"h\0(\x06/a/b/c" + NULL + b"q" + H + F + COLOR + b")z"
    doc = ed.read(compressed(sample() + body))
    s = doc.read_scene(user_data_profile=PROFILE)
    assert s.summary.processed_records == len(s.summary.hsf.records)
    assert len(s.summary.null_shells) == 1 and len(s.summary.rendering_options) == 3
    assert not s.summary.instances and not s.summary.primitive_instances
    assert s.summary.placement_status == "unsupported"
    assert doc.read_scene().summary.processed_records == 3


def test_cli_and_null_shell_limits(tmp_path):
    path = tmp_path / "render.hsf"
    path.write_bytes(raw(NULL + b"q" + H + b"\0"))
    result = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path)],
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(result.stdout)
    assert data["null_shells"][0]["lod"] == 0
    assert data["rendering_options"][0]["kind"] == "heuristics"
    with pytest.raises(ed.LimitExceededError):
        ed.read(raw(NULL + b"\0"), limits=ed.Limits(max_scene_meshes=0)).read_scene()
