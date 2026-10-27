import io
import json
import struct
import subprocess
import sys
import zipfile
import zlib

import edrawings_kit as ed
import pytest
from test_user_data_audit import audit, sample, view

PROFILE = "edrawings_first_be_v2"
POINTS = struct.pack("<6f", 1, 2, 3, 4, 5, 6)


def raw(body):
    return b";; HSF V19.10 \n" + body


def compressed(body):
    return raw(b"I\x04\0\0\0B\0" + bytes(24) + b"Z" + zlib.compress(body) + b"\0")


@pytest.mark.parametrize("wrapper", ["raw", "zip", "prefixed"])
def test_view_dto_sources_and_handedness_inheritance(wrapper):
    hsf = raw(b"h\x01(\x01a" + view(flags=31) + b"h\x00l" + POINTS + b")\0")
    data = hsf
    if wrapper != "raw":
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("eModel", hsf)
        data = stream.getvalue()
        if wrapper == "prefixed":
            # Same independently authored prefix profile as container tests.
            from conftest import PREFIX

            data = PREFIX + data
    doc = ed.read(data)
    s = doc.read_scene(mode="strict")
    v = s.summary.views[0]
    assert isinstance(v, ed.NamedView) and isinstance(v.camera, ed.Camera)
    assert v.name.value == "default" and s.source_bytes(v.name.source) == b"default"
    assert s.source_bytes(v.camera_source) == view(flags=31)[2:-8]
    assert v.camera.projection == "perspective" and v.camera.stretched is True
    assert v.camera.position == (0, 0, 1)
    assert v.camera.up_vector == (0, 1, 0)
    assert v.camera.field_width == 10 and v.camera.field_height == 20
    assert v.camera.oblique_x_degrees == v.camera.oblique_y_degrees == 2
    assert v.camera.near_limit == 2  # Ratio, not clamped to [0, 1].
    assert s.summary.nodes[0].world_handedness.value == "right"
    i = s.summary.primitive_instances[0]
    assert i.world_handedness.value == "left"
    assert s.source_bytes(i.world_handedness.source) == b"h\x00"
    assert s.primitive_points(i.primitive_id).data == POINTS
    assert s.summary.placement_status == "complete"
    assert not s.summary.opaque_user_data
    assert doc.read_drawing().summary.assessment.view_status == "unsupported"


@pytest.mark.parametrize("anchor", [b"h\x00", b"h\x01", view()])
def test_user_data_allows_only_definition_inventory_after_verified_anchor(anchor):
    block = bytearray(sample())
    fields = audit.inspect_header(block, "19.10")["fields"]
    offset = next(f["offset"] for f in fields if f["label"] == "matrix_candidate")
    block[offset : offset + 4] = struct.pack("<f", 42)
    data = compressed(bytes(block) + anchor + b"l" + POINTS + b"z")
    doc = ed.read(data)
    s = doc.read_scene(user_data_profile=PROFILE)
    assert s.summary.status == "partial"
    assert s.summary.placement_status == "unsupported"
    assert s.summary.processed_records == len(s.summary.hsf.records)
    assert len(s.summary.primitives) == 1
    assert not s.summary.instances and not s.summary.primitive_instances
    assert s.primitive_points(s.summary.primitives[0].id).data == POINTS
    assert s.summary.nodes[0].local_transform is None
    opaque = s.summary.opaque_user_data[0]
    assert isinstance(opaque, ed.OpaqueUserData)
    assert s.source_bytes(opaque.source) == block
    assert s.summary.hsf.unparsed == ()
    assert doc.read_scene().summary.processed_records == 3
    with pytest.raises(ed.UnsupportedFeatureError):
        doc.read_scene(mode="strict", user_data_profile=PROFILE)


@pytest.mark.parametrize(
    "suffix", [b"!", b"h\x02", b"}\x20", b"U\x01\0x" + view(), b"l" + POINTS]
)
def test_no_anchor_never_authorizes_user_data_continuation(suffix):
    doc = ed.read(compressed(sample() + suffix + b"z"))
    s = doc.read_scene(user_data_profile=PROFILE)
    assert s.summary.processed_records == 3
    assert s.summary.placement_status == "unsupported"
    assert not s.summary.opaque_user_data and not s.summary.views
    assert not s.summary.primitives
    assert s.summary.diagnostics[-1].code == "hsf.user_data_semantics"


def test_invalid_following_view_and_resource_exhaustion_are_errors():
    for record in [view(width=float("inf")), view(width=0)]:
        with pytest.raises(ed.InvalidFormatError):
            ed.read(compressed(sample() + record + b"z")).read_scene(
                user_data_profile=PROFILE
            )
    with pytest.raises(ed.InvalidFormatError):
        ed.read(compressed(sample() + b"}")).read_scene(user_data_profile=PROFILE)
    doc = ed.read(
        compressed(sample() + view() + b"z"), limits=ed.Limits(max_scene_views=0)
    )
    with pytest.raises(ed.LimitExceededError) as e:
        doc.read_scene(user_data_profile=PROFILE)
    assert e.value.diagnostic.code == "hsf.limit_views"


def test_views_cli_and_unknown_name(tmp_path):
    path = tmp_path / "view.hsf"
    path.write_bytes(raw(view(name=b"\xff") + b"\0"))
    run = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "scene", str(path)],
        capture_output=True,
        encoding="utf-8",
    )
    assert run.returncode == 0, run.stderr
    s = json.loads(run.stdout)
    assert s["views"][0]["name"]["value"] is None
    assert s["views"][0]["name"]["status"] == "unsupported"
    assert s["diagnostics"][0]["code"] == "hsf.view_name_encoding"
