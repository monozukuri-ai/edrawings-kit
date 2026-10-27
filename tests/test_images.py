"""Image profile tests; the tiny JPEG was independently generated with Pillow."""

import base64
import gc
import io
import json
import struct
import subprocess
import sys
import zipfile

import edrawings_kit as ed
import pytest
from test_views import compressed, raw

IMAGE = "edrawings_1910_u32_v1"
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/wAARCAACAAMDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwDPooor9APjD//Z"
)


def image(*, alpha=b"\0\xff", jpeg=JPEG, width=3, height=2, flags=0xA3, compression=2):
    return (
        b"i"
        + struct.pack("<3fIB", 1, 2, 3, flags, 4)
        + b"tile"
        + struct.pack("<iiBi", width, height, compression, len(jpeg))
        + jpeg
        + alpha
    )


def parse(body, **kwargs):
    return ed.read(raw(body + b"\0")).parse_hsf(image_profile=IMAGE, **kwargs)


@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
@pytest.mark.parametrize(
    "alpha", [b"\0\xff", b"\1\2\0\0\0\xfd\x80", b"\1\x07\0\0\0\6abcdef"]
)
def test_image_sources_lifetime_and_next_record(wrapper, alpha):
    body = image(alpha=alpha)
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"h\1\0")
    if wrapper in ("zip", "prefixed"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("eModel", data)
        data = buf.getvalue()
        if wrapper == "prefixed":
            from conftest import PREFIX

            data = PREFIX + data
    doc = ed.read(data)
    hsf = doc.parse_hsf(image_profile=IMAGE)
    del doc
    gc.collect()
    r = next(r for r in hsf.summary.records if r.image)
    i = r.image
    assert isinstance(i, ed.ImageLayout)
    assert (i.width, i.height, i.format_options, i.compression) == (3, 2, 163, 2)
    assert i.profile == "u32_rgba_jpeg_v1"
    assert hsf.source_bytes(i.position) == struct.pack("<3f", 1, 2, 3)
    assert hsf.source_bytes(i.name) == b"tile"
    assert hsf.source_bytes(i.data) == JPEG
    assert hsf.source_bytes(i.alpha) == (alpha[1:] if alpha[0] == 0 else alpha[5:])
    assert hsf.source_bytes(r.source) == body
    assert hsf.summary.stages.hsf_syntax == "partial" and not hsf.summary.unparsed
    assert hsf.summary.diagnostics[0].code == "hsf.experimental_image"
    assert hsf.summary.records[-1].opcode == 0


@pytest.mark.parametrize("method", ["parse_hsf", "read_scene", "read_drawing"])
def test_default_strict_and_invalid_choice(method):
    doc = ed.read(raw(image() + b"\0"))
    default = getattr(doc, method)().summary
    syntax = (
        default
        if method == "parse_hsf"
        else default.hsf
        if method == "read_scene"
        else default.scene.hsf
    )
    assert not syntax.records and syntax.diagnostics[-1].code == "hsf.unknown_opcode"
    with pytest.raises(ed.UnsupportedFeatureError) as err:
        getattr(doc, method)(mode="strict", image_profile=IMAGE)
    assert err.value.diagnostic.code == "hsf.experimental_image"
    with pytest.raises(ValueError, match="image_profile"):
        getattr(doc, method)(image_profile="auto")


@pytest.mark.parametrize("mode", ["strict", "partial"])
@pytest.mark.parametrize("alpha", [b"\0\xff", b"\1\2\0\0\0\xfd\x80"])
def test_every_operand_truncation(mode, alpha):
    record = image(alpha=alpha)
    for end in range(1, len(record)):
        with pytest.raises(ed.InvalidFormatError) as err:
            ed.read(raw(record[:end])).parse_hsf(mode=mode, image_profile=IMAGE)
        assert err.value.diagnostic.classification == "invalid"
        assert err.value.diagnostic.opcode == ord("i")
        assert err.value.diagnostic.byte_range.offset == len(raw(b""))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"width": 0},
        {"height": -1},
        {"width": 4},
        {"jpeg": b"bad"},
        {"jpeg": JPEG[:-2]},
        {"jpeg": JPEG + b"\0"},
        {"alpha": b"\1\2\0\0\0\xfc\x80"},  # 7 instead of 6
        {"alpha": b"\1\2\0\0\0\xfe\x80"},  # 5 instead of 6
        {"alpha": b"\1\1\0\0\0\0"},
        {"alpha": b"\1\0\0\0\0"},
    ],
)
def test_corrupt_recognized_layout_is_invalid(kwargs):
    for mode in ("strict", "partial"):
        with pytest.raises(ed.InvalidFormatError):
            parse(image(**kwargs), mode=mode)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"flags": 0xB3},
        {"flags": 0x1A3},
        {"flags": 0xA4},
        {"compression": 0},
        {"compression": 99},
        {"alpha": b"\2"},
        {"jpeg": JPEG.replace(b"\xff\xc0", b"\xff\xc2")},
    ],
)
def test_unknown_profiles_stop_at_original_image(kwargs):
    h = parse(image(**kwargs))
    assert not h.summary.records
    assert h.summary.diagnostics[-1].code == "hsf.image_profile"
    assert h.summary.domains[0].parsed_bytes == len(raw(b""))


@pytest.mark.parametrize("version", ["8.05", "14.50"])
def test_version_does_not_activate_modern_layout(version):
    data = f";; HSF V{version} \n".encode() + image() + b"\0"
    h = ed.read(data).parse_hsf(image_profile=IMAGE)
    assert (
        not h.summary.records and h.summary.diagnostics[-1].code == "hsf.image_profile"
    )


def test_limits_are_separate_cumulative_and_include_zero():
    data = raw(image() * 2 + b"\0")
    for maximum in (0, 5, 11):
        with pytest.raises(ed.LimitExceededError) as err:
            ed.read(data, limits=ed.Limits(max_hsf_image_pixels=maximum)).parse_hsf(
                image_profile=IMAGE
            )
        assert err.value.diagnostic.code == "hsf.limit_image_pixels"
    assert (
        len(
            ed.read(data, limits=ed.Limits(max_hsf_image_pixels=12, max_hsf_vertices=0))
            .parse_hsf(image_profile=IMAGE)
            .summary.records
        )
        == 3
    )
    with pytest.raises(ed.LimitExceededError):
        ed.read(data, limits=ed.Limits(max_hsf_string_bytes=3)).parse_hsf(
            image_profile=IMAGE
        )
    with pytest.raises(ed.LimitExceededError):
        ed.read(data, limits=ed.Limits(max_output_bytes=0)).parse_hsf(
            image_profile=IMAGE
        )


def test_nonfinite_position_and_negative_length_are_invalid():
    for at, value in [
        (1, struct.pack("<f", float("nan"))),
        (31, struct.pack("<i", -1)),
    ]:
        b = bytearray(image())
        b[at : at + 4] = value
        with pytest.raises(ed.InvalidFormatError):
            parse(bytes(b))


def test_scene_image_tag_is_distinct_from_previous_geometry():
    body = b"X" + bytes(12) + image() + b"qr\0\0\0\0\0"
    scene = ed.read(raw(body)).read_scene(image_profile=IMAGE)
    assert scene.summary.processed_records == len(scene.summary.hsf.records)
    assert scene.summary.diagnostics[-1].code == "hsf.image_inventory"
    assert scene.summary.references[0].target_id == scene.summary.images[0].id
    assert not scene.summary.primitive_instances
    assert len(scene.summary.primitives) == 1
    assert scene.summary.placement_status == "unsupported"


def test_alpha_zero_control_repeats_three_values():
    r = parse(image(alpha=b"\1\4\0\0\0\0a\0b")).summary.records[0]
    assert r.image.alpha.length == 4


@pytest.mark.parametrize("command", ["hsf", "scene", "drawing"])
def test_cli_exposes_explicit_image_profile(tmp_path, command):
    path = tmp_path / "image.hsf"
    path.write_bytes(raw(image() + b"\0"))
    cli = subprocess.run(
        [
            sys.executable,
            "-m",
            "edrawings_kit",
            command,
            str(path),
            "--image-profile",
            IMAGE,
        ],
        capture_output=True,
        encoding="utf-8",
        check=True,
    )
    method = {"hsf": "parse_hsf", "scene": "read_scene", "drawing": "read_drawing"}[
        command
    ]
    assert (
        json.loads(cli.stdout)
        == getattr(ed.read_file(path, read_metadata=False), method)(
            image_profile=IMAGE
        ).summary.to_dict()
    )
