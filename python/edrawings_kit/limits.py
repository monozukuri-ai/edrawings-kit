"""Per-operation limits. Zero allows no consumption; it never means unlimited."""

from dataclasses import dataclass, fields


@dataclass(frozen=True)
class Limits:
    max_hsf_image_pixels: int = 16_777_216
    max_hsf_vertices: int = 10_000_000
    max_hsf_face_values: int = 50_000_000
    max_scene_meshes: int = 250_000
    max_scene_primitives: int = 250_000
    max_scene_views: int = 10_000
    max_scene_definitions: int = 10_000
    max_scene_nodes: int = 250_000
    max_scene_instances: int = 1_000_000
    max_scene_depth: int = 256
    max_scene_visits: int = 2_000_000
    max_scene_triangles: int = 10_000_000
    max_file_bytes: int = 256 << 20
    max_entries: int = 4096
    max_entry_bytes: int = 256 << 20
    max_expanded_bytes: int = 512 << 20
    max_output_bytes: int = 3072 << 20
    max_compression_ratio: int = 1000
    max_name_bytes: int = 4096
    max_xml_bytes: int = 8 << 20
    max_xml_depth: int = 128
    max_xml_elements: int = 100_000
    max_hsf_records: int = 1_000_000
    max_hsf_domains: int = 128
    max_hsf_segment_depth: int = 256
    max_hsf_string_bytes: int = 16 << 20

    def __post_init__(self) -> None:
        for field in fields(self):
            value = getattr(self, field.name)
            if type(value) is not int or not 0 <= value <= (1 << 64) - 1:
                raise ValueError(f"{field.name} must be an unsigned 64-bit integer")

    @classmethod
    def desktop(cls) -> "Limits":
        return cls()

    @classmethod
    def service(cls) -> "Limits":
        return cls(
            max_hsf_vertices=1_000_000,
            max_hsf_image_pixels=4_194_304,
            max_hsf_face_values=5_000_000,
            max_scene_meshes=250_000,
            max_scene_primitives=250_000,
            max_scene_views=1_000,
            max_scene_definitions=1_000,
            max_scene_nodes=250_000,
            max_scene_instances=1_000_000,
            max_scene_depth=64,
            max_scene_visits=5_000_000,
            max_scene_triangles=10_000_000,
            max_file_bytes=32 << 20,
            max_entries=512,
            max_entry_bytes=64 << 20,
            max_expanded_bytes=256 << 20,
            max_output_bytes=2560 << 20,
            max_compression_ratio=200,
            max_name_bytes=1024,
            max_xml_bytes=2 << 20,
            max_xml_depth=64,
            max_xml_elements=20_000,
            max_hsf_records=2_000_000,
            max_hsf_domains=32,
            max_hsf_segment_depth=64,
            max_hsf_string_bytes=2 << 20,
        )
