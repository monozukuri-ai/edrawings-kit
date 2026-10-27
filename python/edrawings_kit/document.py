from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from . import _core
from .errors import _native_errors
from .models import (
    DrawingSummary,
    Extraction,
    ExtractionInfo,
    HsfInspection,
    HsfSpan,
    HsfSummary,
    Inspection,
    MeshBuffers,
    NumericBuffer,
    SceneSummary,
    XmlMetadata,
    _decode,
)


@dataclass(frozen=True)
class Document:
    """Owns the input bytes; extraction never reopens the source path.

    Repeated operations have independent budgets. verify_all() shares one budget
    across entries. No unbounded decoded payload cache is retained.
    """

    _handle: _core.DocumentHandle

    @property
    def inspection(self) -> Inspection:
        return _decode(Inspection, self._handle.inspection_json())

    @property
    def metadata(self) -> tuple[XmlMetadata, ...]:
        return tuple(
            _decode(XmlMetadata, json.dumps(item))
            for item in json.loads(self._handle.metadata_json())
        )

    def extract(self, entry_id: str) -> Extraction:
        with _native_errors():
            data, info = self._handle.extract(entry_id)
        return Extraction(data, _decode(ExtractionInfo, info))

    def verify_all(self) -> tuple[ExtractionInfo, ...]:
        with _native_errors():
            values = self._handle.verify_all_json()
        return tuple(
            _decode(ExtractionInfo, json.dumps(item)) for item in json.loads(values)
        )

    def inspect_hsf(self, entry_id: str | None = None) -> HsfInspection:
        """CRC-check and identify an HSF header. Does not parse HSF opcodes."""
        with _native_errors():
            return _decode(HsfInspection, self._handle.inspect_hsf_json(entry_id))

    def parse_hsf(
        self,
        entry_id: str | None = None,
        *,
        mode: Literal["strict", "partial"] = "partial",
        user_data_profile: Literal[
            "disabled", "edrawings_first_be_v2", "edrawings_be_envelope_v1"
        ] = "disabled",
        image_profile: Literal["disabled", "edrawings_1910_u32_v1"] = "disabled",
    ) -> HsfDocument:
        """Parse bounded syntax. Partial stops at unknown framing; strict rejects it.

        Both modes reject corrupt input and resource exhaustion. Syntax completion
        makes no claim about geometry, reference resolution, or product semantics.
        edrawings_first_be_v2 opts into empirical first-header framing, always
        partial and rejected in strict mode. Raw field spans preserve unknowns.
        edrawings_be_envelope_v1 additionally recognizes a closed terminal zero
        envelope before compressed/file termination, also opaque and partial.
        edrawings_1910_u32_v1 opts into observed named RGBA/JPEG image framing,
        also partial only. Encoded image spans do not imply decoded pixels.
        """
        with _native_errors():
            handle = self._handle.parse_hsf(
                entry_id, mode, user_data_profile, image_profile
            )
        return HsfDocument(_decode(HsfSummary, handle.summary_json()), handle)

    def read_scene(
        self,
        entry_id: str | None = None,
        *,
        mode: Literal["strict", "partial"] = "partial",
        user_data_profile: Literal[
            "disabled", "edrawings_first_be_v2", "edrawings_be_envelope_v1"
        ] = "disabled",
        image_profile: Literal["disabled", "edrawings_1910_u32_v1"] = "disabled",
        import_root: str | None = None,
    ) -> SceneResult:
        """Read generic meshes and drawing primitives. Unknown units stay None.

        Coordinates and normals are local; apply each instance's row-vector
        world_transform once. Check status and diagnostics before using geometry.
        Named views are stored presets, not active cameras or CAD drawing views.
        An accepted first User Data header followed by h / } enables inventory
        only: opaque_user_data is retained and placement_status is unsupported.
        Mesh and primitive definitions may be present while instances stay empty.

        import_root supplies an absolute segment path for partial inventory only.
        It does not load external state or verify the producer's import location.
        The supplied context is retained and all placements are withheld.
        """
        with _native_errors():
            handle = self._handle.read_scene(
                entry_id, mode, user_data_profile, image_profile, import_root
            )
        return SceneResult(_decode(SceneSummary, handle.summary_json()), handle)

    def read_drawing(
        self,
        entry_id: str | None = None,
        *,
        mode: Literal["strict", "partial"] = "partial",
        user_data_profile: Literal[
            "disabled", "edrawings_first_be_v2", "edrawings_be_envelope_v1"
        ] = "disabled",
        image_profile: Literal["disabled", "edrawings_1910_u32_v1"] = "disabled",
        import_root: str | None = None,
    ) -> DrawingResult:
        """Inventory primitives and options with partial native drawing semantics.

        Strict also requires sheet/view, dimension and product mappings, currently
        unsupported. Use read_scene(strict) to validate generic geometry alone.

        import_root supplies an absolute segment path for partial inventory only.
        It does not load external state or verify the producer's import location.
        The supplied context is retained and all placements are withheld.
        """
        with _native_errors():
            handle = self._handle.read_drawing(
                entry_id, mode, user_data_profile, image_profile, import_root
            )
        return DrawingResult(_decode(DrawingSummary, handle.summary_json()), handle)


@dataclass(frozen=True)
class HsfDocument:
    """Immutable summary plus owned source domains, valid after Document is dropped."""

    summary: HsfSummary
    _handle: _core.HsfHandle

    def source_bytes(self, span: HsfSpan) -> bytes:
        """Copy a checked domain range, including raw strings and opaque user data."""
        with _native_errors():
            return self._handle.source_bytes(span.domain_id, span.offset, span.length)


@dataclass(frozen=True)
class SceneResult:
    summary: SceneSummary
    _handle: _core.SceneHandle

    def shell_parameters(self, set_id: str) -> NumericBuffer:
        """Source Shell vertex order; metadata reports the geometry binding status."""
        with _native_errors():
            data = self._handle.shell_parameters(set_id)
        metadata = next(
            s.vertex_parameters
            for s in self.summary.shell_parameter_sets
            if s.id == set_id
        )
        return NumericBuffer(data, "<f4", (metadata.count, metadata.width))

    def source_bytes(self, span: HsfSpan) -> bytes:
        with _native_errors():
            return self._handle.source_bytes(span.domain_id, span.offset, span.length)

    def primitive_points(self, primitive_id: str) -> NumericBuffer:
        """Copy original local XYZ coordinates; no flattening or curve tessellation."""
        with _native_errors():
            data = self._handle.primitive_points(primitive_id)
        primitive = next(p for p in self.summary.primitives if p.id == primitive_id)
        return NumericBuffer(data, "<f4", (primitive.point_count, 3))

    def mesh_buffers(self, mesh_id: str) -> MeshBuffers:
        """Copy native arrays to immutable, little-endian bytes (no NumPy required).

        Faces preserve original counts and indices. triangle_faces links each
        generated triangle to its source face/strip/fan. Normals are optional,
        unmodified local vertex normals; they are never synthesized.
        Parameters are optional raw or dequantized f32 tuples, without clamping,
        V inversion, generated UV, or texture-matrix application.
        """
        with _native_errors():
            vertices = self._handle.buffer(mesh_id, "vertices")
            mesh = self.summary.meshes[self._handle.mesh_index(mesh_id)]
            return MeshBuffers(
                NumericBuffer(vertices, "<f4", (mesh.vertex_count, 3)),
                NumericBuffer(
                    self._handle.buffer(mesh_id, "face_list"),
                    "<i4",
                    (mesh.face_value_count,),
                ),
                NumericBuffer(
                    self._handle.buffer(mesh_id, "triangles"),
                    "<u4",
                    (mesh.triangle_count, 3),
                ),
                NumericBuffer(
                    self._handle.buffer(mesh_id, "triangle_faces"),
                    "<u4",
                    (mesh.triangle_count,),
                ),
                NumericBuffer(
                    self._handle.buffer(mesh_id, "normals"),
                    "<f4",
                    (mesh.normal_count, 3),
                )
                if mesh.normal_count
                else None,
                NumericBuffer(
                    self._handle.buffer(mesh_id, "parameters"),
                    "<f4",
                    (mesh.vertex_parameters.count, mesh.vertex_parameters.width),
                )
                if mesh.vertex_parameters is not None
                else None,
            )


@dataclass(frozen=True)
class DrawingResult:
    summary: DrawingSummary
    _handle: _core.DrawingHandle

    def source_bytes(self, span: HsfSpan) -> bytes:
        with _native_errors():
            return self._handle.source_bytes(span.domain_id, span.offset, span.length)

    def primitive_points(self, primitive_id: str) -> NumericBuffer:
        """Original XYZ points; transforms and unresolved projection are separate."""
        with _native_errors():
            data = self._handle.primitive_points(primitive_id)
        primitive = next(
            p for p in self.summary.scene.primitives if p.id == primitive_id
        )
        return NumericBuffer(data, "<f4", (primitive.point_count, 3))
