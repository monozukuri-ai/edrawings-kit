"""Records of eDrawings drawings and third-party publishers through the Python API.

Streams are authored here: named JPEG images without alpha, elliptical arcs,
quantized batch and Mesh points, and UTF-16 text code 8.
"""

import struct

import edrawings_kit as ed
from test_images import IMAGE, JPEG, image


def stream(body, version="19.10"):
    return f";; HSF V{version} \n".encode() + body + b"\0"


def packed16(codes):
    """16-bit codes in little-endian 32-bit words, most significant first."""
    words = [0] * ((len(codes) * 16 + 31) // 32)
    for i, code in enumerate(codes):
        words[i // 2] |= code << (16 if i % 2 == 0 else 0)
    return struct.pack(f"<{len(words)}I", *words)


def test_named_jpeg_image_has_no_alpha():
    body = image(flags=0x87, alpha=b"") + b"h\x01"
    for version in ("19.00", "19.10"):
        doc = ed.read(stream(body, version))
        hsf = doc.parse_hsf(image_profile=IMAGE)
        layout = hsf.summary.records[0].image
        assert layout.profile == "u32_jpeg_v1"
        assert (layout.alpha_compression, layout.alpha) == (None, None)
        assert hsf.source_bytes(layout.data) == JPEG
        assert hsf.summary.records[1].kind == "handedness"
        scene = doc.read_scene(image_profile=IMAGE)
        definition = scene.summary.images[0]
        assert definition.alpha_source is None
        assert definition.implicit_texture_local is False
        assert definition.to_dict()["alpha_compression"] is None


def test_elliptical_arc_keeps_axis_points_and_limits():
    points = struct.pack("<9f", 5, 5, 0, 9, 5, 0, 5, 7, 0)
    body = b"E" + points + b"e" + points + struct.pack("<2f", 0.25, 0.75)
    drawing = ed.read(stream(body)).read_drawing()
    ellipse, arc = drawing.summary.scene.primitives
    assert (ellipse.kind, arc.kind) == ("ellipse", "elliptical_arc")
    assert ellipse.limits is None
    assert arc.limits.value == (0.25, 0.75)
    assert drawing.source_bytes(arc.limits.source) == struct.pack("<2f", 0.25, 0.75)
    assert drawing.primitive_points(arc.id).data == points
    layout = ed.read(stream(body)).parse_hsf().summary.records[1].primitive
    assert layout.limits is not None and layout.limits.length == 8


def test_quantized_batch_points_and_values_decode_in_the_scene():
    # Y unrestricted (codes over 0..8), X per component (10 and 20), Z zero.
    body = (
        b"\x10"
        + struct.pack("<H3i", 0x1301, 4, 2, 2)
        + b"\x01"
        + struct.pack("<2f", 0, 8)
        + struct.pack("<2i", 16, 8)
        + packed16([0, 0xFFFF, 0, 0xFFFF])
        + b"\x01"
        + struct.pack("<2f", 10, 20)
        + struct.pack("<i", 4)
        + packed16([0, 0xFFFF])
    )
    doc = ed.read(stream(body, "19.00"))
    layout = doc.parse_hsf(mode="strict").summary.records[0].poly_polyline
    assert layout.point_quantization.bits_per_sample == 16
    assert layout.leftover_quantization.bits_per_sample == 16
    scene = doc.read_scene(mode="strict")
    batch = scene.summary.primitives[0]
    assert scene.primitive_points(batch.id).data == struct.pack(
        "<12f", 10, 0, 0, 10, 8, 0, 20, 0, 0, 20, 8, 0
    )


def test_quantized_mesh_points_decode_within_their_box():
    codes = packed16([0, 0, 0, 0xFFFF, 0, 0, 0, 0xFFFF, 0, 0xFFFF, 0xFFFF, 0])
    body = (
        b"M\x01"
        + struct.pack("<2i", 2, 2)
        + b"\x01"
        + struct.pack("<i6f", 4, 1, 2, 0, 3, 6, 0)
        + b"\x10"
        + struct.pack("<i", len(codes))
        + codes
    )
    doc = ed.read(stream(body, "19.00"))
    layout = doc.parse_hsf(mode="strict").summary.records[0].mesh
    assert layout.point_quantization.bits_per_sample == 16
    scene = doc.read_scene(mode="strict")
    mesh = scene.summary.meshes[0]
    assert scene.mesh_buffers(mesh.id).vertices.data == struct.pack(
        "<12f", 1, 2, 0, 3, 2, 0, 1, 6, 0, 3, 6, 0
    )


def test_text_code_8_decodes_as_utf16():
    label = "Note 寸法".encode("utf-16-le")
    body = b"x" + struct.pack("<3f", 1, 2, 3) + bytes([8, len(label)]) + label + b"\0"
    text = ed.read(stream(body, "18.00")).read_scene().summary.primitives[0].text
    assert (text.encoding, text.encoding_code, text.value) == (
        "utf_16_le",
        8,
        "Note 寸法",
    )
