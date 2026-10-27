# Python API guide

English | [日本語](ja/api.md)

`edrawings_kit` parses input in Rust and returns immutable Python dataclasses and
byte buffers. Summary and metadata models provide `to_dict()` to produce
JSON-compatible dictionaries. Public types include type annotations.

## Inputs and entries

```python
import edrawings_kit as ed

info = ed.inspect_file("part.eprt")
doc = ed.read_file("part.eprt", limits=ed.Limits.desktop())
for entry in info.entries:
    print(entry.id, entry.name, entry.bytes)

checks = doc.verify_all()
payload = doc.extract(info.hsf_candidates[0])
print(payload.info.sha256, len(payload.data))
```

Use `probe_file`, `inspect_file`, or `read_file` for files, and `probe`, `inspect`, or
`read` for bytes. The format is identified from the contents, not the filename
extension. `read_file` retains a snapshot of the input, so later changes to the
source file do not affect the document.

`inspect` does not decompress entries or check their CRCs. `verify_all()` verifies
all entries; `read_file(..., verify_all=True)` requests the same verification when
reading. ZIP entry names are never used as automatic extraction destinations.
Entries with duplicate names are distinguished by IDs such as `entry:N`.
If there are multiple HSF candidates, select an entry explicitly.

```python
header = doc.inspect_hsf("entry:0")
parsed = doc.parse_hsf("entry:0", mode="partial")
```

## Parse status and errors

| Status | Meaning |
| --- | --- |
| `not_requested` | This stage has not run. |
| `complete` | The supported scope of this stage and profile has been processed. |
| `partial` | Confirmed data is available, but unsupported or missing information remains. |
| `unsupported` | The operation or semantics are not supported. |

`complete` does not mean support for every eDrawings format. Geometry definitions,
placement, rendering settings, and document semantics have separate statuses.
Do not use `scene.status` alone to judge whether rendering can be reproduced.

`InvalidFormatError`, `UnsupportedFeatureError`, and `LimitExceededError` derive
from `EdrawingsError`. Use `error.diagnostic.code` for programmatic error handling.
I/O failures use `OSError` subclasses. Even in `partial` mode, corruption and limit
violations are errors.

```python
try:
    scene = doc.read_scene(mode="strict")
except ed.UnsupportedFeatureError as error:
    print(error.diagnostic.code)
```

## Experimental profiles

`parse_hsf`, `read_scene`, and `read_drawing` accept the following arguments:

| Argument | Value | Purpose |
| --- | --- | --- |
| `user_data_profile` | `disabled` (default) | Do not interpret product-specific User Data. |
| `user_data_profile` | `edrawings_first_be_v2` | Read boundaries and fields of supported leading User Data. |
| `user_data_profile` | `edrawings_be_envelope_v1` | Read supported leading and terminal User Data. |
| `image_profile` | `disabled` (default) | Do not enable experimental image conventions. |
| `image_profile` | `edrawings_1910_u32_v1` | Read stored values and source references for supported image definitions. |

Applying an experimental profile is recorded in diagnostics and rejected in
`strict` mode. Unresolved User Data or rendering settings may prevent instance
placement. The parser does not guess unknown versions or lengths to skip data.

The `import_root` argument to `read_scene` and `read_drawing` supplies an explicit
absolute segment context. It does not fetch external files or infer unknown
parent attributes.

## Meshes and placement

```python
scene = doc.read_scene(user_data_profile="edrawings_be_envelope_v1")
print(scene.summary.status, scene.summary.placement_status)
for mesh in scene.summary.meshes:
    buffers = scene.mesh_buffers(mesh.id)
    print(buffers.vertices.dtype, buffers.vertices.shape)    # <f4, (N, 3)
    print(buffers.triangles.dtype, buffers.triangles.shape)  # <u4, (T, 3)
    vertex_bytes = buffers.vertices.data
```

Buffers are copies stored as immutable bytes; NumPy is optional. If needed, use
`np.frombuffer(buffer.data, dtype=buffer.dtype).reshape(buffer.shape)`.
Vertices use local coordinates. Instances with resolved placement are returned
separately in `scene.summary.instances`. Matrices use row-major storage and row
vectors, with composition order `p_world = p_local * local * parent`.

Unknown units, colors, and visibility remain `None`. The parser does not convert
units or generate normals. Faces that cannot be triangulated retain their original
face data; triangle buffers may be withheld. `triangle_faces` maps generated
triangles to their source faces.

## Drawings, text, and document structure

```python
drawing = doc.read_drawing(user_data_profile="edrawings_be_envelope_v1")
for primitive in drawing.summary.scene.primitives:
    points = drawing.primitive_points(primitive.id)
    if primitive.text is not None:
        print(primitive.text.value, primitive.text.encoding, primitive.text.status)
        raw_text = drawing.source_bytes(primitive.text.source)

print(drawing.summary.sheet_inventory)
print(drawing.summary.component_inventory)
print(drawing.summary.configuration_inventory)
print(drawing.summary.drawing_plane_profile)
```

Sheets, views, components, and configurations are read from supported storage
conventions. Component matrices are local values. The parser does not infer an
active configuration or general effective display state. Drawing XY units are
supported only for writers that meet the profile's validation conditions; recovery
of the original CAD origin or model dimensions is not guaranteed.

Text is decoded strictly using known ASCII, ISO-8859-1, UTF-8, and Unicode16/32
conventions. Unknown encodings retain the original information; malformed data in
a known encoding raises an error. Dimension display text is not converted into
true dimensions, tolerances, or geometric references.

`read_drawing(mode="strict")` requires document semantics and currently raises an
unsupported-feature exception. For strict validation of generic elements, use
`read_scene(mode="strict")` with supported input.

## Source references and resource limits

`source_bytes(span)` returns the original bytes in the specified decompressed
domain. Container offsets and offsets within internally decompressed data use
different coordinate systems; do not add them together.

`Limits.desktop()` and `Limits.service()` set budgets for input, decompression,
output, records, nodes, and other resources. You can also set individual limits
with `Limits(max_file_bytes=..., max_output_bytes=...)`.
These are parser consumption budgets, not limits on the process's total RSS.
JSON serialization and array copies in your application require additional memory.
