"""Entity collections preserve ordered text and opaque product semantics."""

import struct
from dataclasses import FrozenInstanceError

import edrawings_kit as ed
import pytest
from test_rendering import NULL
from test_scene import shell
from test_shell_refinement import refined
from test_views import raw


def options(value, unicode=False, extended=False):
    data = value.encode("utf-16le") if unicode and isinstance(value, str) else value
    count = len(data) // 2 if unicode else len(data)
    return (
        (b"\x16" if unicode else b"U")
        + (
            b"\xff\xff" + struct.pack("<I", count)
            if extended
            else struct.pack("<H", count)
        )
        + data
    )


def with_metadata(fields):
    base = shell()
    return base[:1] + b"\x18" + base[2:] + b"\x63" + fields + b"\0\0"


@pytest.mark.parametrize("extended", [False, True])
@pytest.mark.parametrize("refinement", [False, True])
def test_ordered_metadata_source_and_encoding(extended, refinement):
    fields = (
        options(b"x=one", extended=extended)
        + options("部品=😀", unicode=True, extended=extended)
        + options(b"x=two")
        + options(b"")
    )
    body = with_metadata(fields)
    if refinement:
        body = NULL + b"q" + refined(body)
    scene = ed.read(raw(body + b"\0")).read_scene(mode="strict")
    m = scene.summary.meshes[0]
    meta = m.entity_metadata
    assert isinstance(meta, ed.EntityMetadata) and isinstance(
        meta.fields[0], ed.EntityMetadataField
    )
    assert [f.kind for f in meta.fields] == [
        "user_options",
        "unicode_options",
        "user_options",
        "user_options",
    ]
    assert [f.text.value for f in meta.fields] == ["x=one", "部品=😀", "x=two", ""]
    assert (
        meta.decoding_status == "complete"
        and meta.interpretation_status == "unsupported"
    )
    assert scene.source_bytes(meta.source) == b"\x63" + fields + b"\0"
    for field, expected in zip(
        meta.fields,
        [b"x=one", "部品=😀".encode("utf-16le"), b"x=two", b""],
        strict=True,
    ):
        assert scene.source_bytes(field.text.source) == expected
    assert scene.summary.status == scene.summary.placement_status == "complete"
    assert len(scene.summary.instances) == 1 and not scene.summary.rendering_options
    with pytest.raises(FrozenInstanceError):
        meta.decoding_status = "unsupported"


def test_empty_collection_and_absence_are_distinct():
    scene = ed.read(raw(with_metadata(b"") + shell() + b"\0")).read_scene(mode="strict")
    a, b = scene.summary.meshes
    assert (
        a.entity_metadata.fields == ()
        and a.entity_metadata.decoding_status == "complete"
    )
    assert b.entity_metadata is None


def test_unspecified_non_ascii_is_not_guessed():
    scene = ed.read(raw(with_metadata(options(b"\x82\xa0=x")) + b"\0")).read_scene(
        mode="strict"
    )
    meta = scene.summary.meshes[0].entity_metadata
    text = meta.fields[0].text
    assert (
        meta.decoding_status
        == meta.interpretation_status
        == text.status
        == "unsupported"
    )
    assert text.encoding == "unspecified" and text.value is None
    assert scene.source_bytes(text.source) == b"\x82\xa0=x"
    assert scene.summary.status == "complete"


@pytest.mark.parametrize("mode", ["partial", "strict"])
@pytest.mark.parametrize("bad", [b"\x00\xd8", b"\x00\xdc", b"\x00\xd8A\0"])
def test_malformed_unicode_is_invalid_without_replacement(mode, bad):
    doc = ed.read(raw(with_metadata(options(bad, unicode=True)) + b"\0"))
    assert doc.parse_hsf(mode="strict").summary.stages.hsf_syntax == "complete"
    with pytest.raises(ed.InvalidFormatError) as error:
        doc.read_scene(mode=mode)
    assert error.value.diagnostic.code == "hsf.invalid_text_encoding"


def test_unknown_entity_opcode_does_not_become_metadata():
    doc = ed.read(raw(with_metadata(b"~\x01\x01\x02\x03") + b"\0"))
    with pytest.raises(ed.UnsupportedFeatureError) as error:
        doc.read_scene(mode="strict")
    assert error.value.diagnostic.code == "hsf.shell_entity_attribute"
    assert not doc.read_scene().summary.meshes


def test_metadata_count_and_output_limits():
    body = with_metadata(options(b"x=y") * 33)
    with pytest.raises(ed.LimitExceededError) as error:
        ed.read(raw(body + b"\0")).read_scene()
    assert error.value.diagnostic.code == "hsf.limit_shell_entity_attributes"
    data = raw(with_metadata(options(b"x=" + b"v" * 1000)) + b"\0")
    baseline = ed.read(data).read_scene()
    with pytest.raises(ed.LimitExceededError):
        ed.read(
            data,
            limits=ed.Limits(max_output_bytes=baseline.summary.usage.output_bytes - 1),
        ).read_scene()


def test_cli_exposes_normals_and_metadata(tmp_path):
    import json
    import subprocess
    import sys

    from test_vertex_normals import normal_shell

    body = normal_shell()[0][:-1] + b"\x63" + options(b"x=y") + b"\0\0"
    path = tmp_path / "normals.hsf"
    path.write_bytes(raw(body + b"\0"))
    scene = ed.read_file(path).read_scene(mode="strict")
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path), "--mode", "strict"],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    result = json.loads(run.stdout)
    assert result["meshes"] == [m.to_dict() for m in scene.summary.meshes]
    assert result["status"] == "complete" and result["placement_status"] == "complete"
