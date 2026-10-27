"""Image ownership and raw name correlation do not imply texture evaluation."""

import gc
import struct

import edrawings_kit as ed
import pytest
from test_images import IMAGE, JPEG, image
from test_segment_style import opened
from test_views import compressed, raw


def picture(name=b"tile", **kwargs):
    body = image(**kwargs)
    return body[:17] + bytes([len(name)]) + name + body[22:]


def texture(name=b"tile"):
    return b"t\x03tex" + bytes([len(name)]) + name + b"\0\0"


def read(body, **kwargs):
    return ed.read(raw(body + b"\0"), **kwargs).read_scene(image_profile=IMAGE)


@pytest.mark.parametrize("wrapper", ["raw", "compressed", "zip", "prefixed"])
@pytest.mark.parametrize("alpha", [b"\0\xff", b"\1\2\0\0\0\xfd\x80"])
def test_image_inventory_owned_spans_and_continuation(wrapper, alpha, zip_factory):
    body = opened(b"images") + picture(alpha=alpha) + b")X" + bytes(12)
    data = compressed(body + b"z") if wrapper == "compressed" else raw(body + b"\0")
    if wrapper in ("zip", "prefixed"):
        data = zip_factory([("eModel", data)], prefix=wrapper == "prefixed")
    doc = ed.read(data)
    scene = doc.read_scene(image_profile=IMAGE)
    del doc
    gc.collect()
    s = scene.summary
    assert s.processed_records == len(s.hsf.records)
    assert s.status == "partial" and s.placement_status == "unsupported"
    assert not s.instances and not s.primitive_instances
    assert len(s.primitives) == 1
    resource = s.images[0]
    assert isinstance(resource, ed.ImageDefinition)
    assert resource.node_id == s.nodes[1].id
    assert resource.interpretation_status == "unsupported"
    assert resource.position.value == (1, 2, 3)
    assert resource.implicit_texture_local and resource.format_options == 0xA3
    assert (resource.width, resource.height, resource.compression) == (3, 2, 2)
    assert resource.profile == "u32_rgba_jpeg_v1"
    assert scene.source_bytes(resource.source) == picture(alpha=alpha)
    assert scene.source_bytes(resource.name.source) == b"tile"
    assert scene.source_bytes(resource.data_source) == JPEG
    assert scene.source_bytes(resource.position.source) == struct.pack("<3f", 1, 2, 3)
    assert scene.source_bytes(resource.alpha_source) == (
        alpha[1:] if alpha[0] == 0 else alpha[5:]
    )
    r = next(r for r in s.hsf.records if r.id == resource.source_record_id)
    assert r.image.alpha == resource.alpha_source and r.source == resource.source
    assert [d.code for d in s.diagnostics] == [
        "hsf.experimental_image",
        "hsf.image_inventory",
    ]
    assert all(d.severity == "warning" for d in s.diagnostics)
    assert not s.textures  # No synthetic Texture opcode is fabricated.


@pytest.mark.parametrize("before", [False, True])
@pytest.mark.parametrize("name", [b"tile", b"\xff\xfe", b"a\0b"])
def test_exact_name_candidates_allow_forward_order_and_preserve_raw_names(before, name):
    body = texture(name) + picture(name) if before else picture(name) + texture(name)
    scene = read(body)
    s = scene.summary
    assert s.textures[0].image_name_matches == (s.images[0].id,)
    assert s.images[0].name.value == (name.decode() if name.isascii() else None)
    assert scene.source_bytes(s.textures[0].image.source) == name
    assert scene.source_bytes(s.images[0].name.source) == name
    assert s.textures[0].interpretation_status == "unsupported"


def test_multiple_candidates_preserve_order_without_scope_or_override_guess():
    s = read(
        texture() + opened(b"a") + picture() + b")" + opened(b"b") + picture() + b")"
    ).summary
    assert s.textures[0].image_name_matches == tuple(i.id for i in s.images)
    assert s.images[0].node_id != s.images[1].node_id
    assert s.images[0].id != s.images[1].id
    assert not s.instances and not s.primitive_instances


@pytest.mark.parametrize("name", [b"missing", b"TILE", b"tile ", b" tile"])
def test_name_matching_does_not_invent_image_name_normalization(name):
    assert read(texture(name) + picture()).summary.textures[0].image_name_matches == ()


def test_candidates_are_limited_to_consumed_scene_prefix():
    scene = read(texture() + picture() + opened(b"../outside") + picture() + b")")
    s = scene.summary
    assert len(s.images) == 1
    assert sum(r.image is not None for r in s.hsf.records) == 2
    assert s.textures[0].image_name_matches == (s.images[0].id,)
    assert s.diagnostics[-1].code == "hsf.segment_path"


def test_compression_and_unsupported_syntax_suffix_keep_image_inventory():
    doc = ed.read(compressed(texture() + picture() + b"\xffz"))
    s = doc.read_scene(image_profile=IMAGE).summary
    assert s.hsf.unparsed and len(s.images) == 1
    assert s.textures[0].image_name_matches == (s.images[0].id,)


def test_close_restores_segment_tag_target_and_image_cannot_reopen_segment():
    s = read(opened(b"owner") + picture() + b")qr\0\0\0\0").summary
    assert s.references[0].target_id == s.nodes[1].id
    assert s.references[0].target_id != s.images[0].id
    blocked = read(picture() + b"qs\0\0\0\0X" + bytes(12) + b")").summary
    assert blocked.processed_records == 2 and not blocked.primitives
    assert blocked.diagnostics[-1].code == "hsf.unresolved_reopen"


def test_repeat_does_not_transform_an_image_into_geometry():
    repeat = b"&" + struct.pack(
        "<4iB12f", 0, 0, -1, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0
    )
    s = read(picture() + b"q" + repeat).summary
    assert s.references[0].target_id is None
    assert s.diagnostics[-1].code == "hsf.repeat_target"
    assert not s.meshes and not s.primitives and not s.instances


@pytest.mark.parametrize(
    "body,maximum",
    [
        (picture(), 0),
        (picture() * 2, 1),
        (picture() + texture(), 1),
        (texture() + picture(), 1),
        (picture() + b"{\x01/", 1),
        (b"{\x01/" + picture(), 1),
        (opened(b"?Home") + picture() + b")", 1),
    ],
)
def test_image_shares_definition_limit_with_other_resources(body, maximum):
    with pytest.raises(ed.LimitExceededError) as err:
        read(body, limits=ed.Limits(max_scene_definitions=maximum))
    assert err.value.diagnostic.code == "hsf.limit_definitions"


def test_ambiguous_name_matches_charge_output_budget_before_allocating():
    body = picture() * 30 + texture() * 30
    scene = read(body)
    assert all(len(t.image_name_matches) == 30 for t in scene.summary.textures)
    # Distinct names have identical wire sizes but no candidate pair allocations.
    distinct = picture() * 30 + texture(b"none") * 30
    smaller = read(distinct).summary.usage.output_bytes
    assert smaller < scene.summary.usage.output_bytes
    with pytest.raises(ed.LimitExceededError):
        read(body, limits=ed.Limits(max_output_bytes=smaller))
