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

## Display bundles

`read_display()` builds what a viewer needs from one bounded read: bodies as
packed local buffers and estimated instance placements for one saved
configuration, with colours and names.

```python
display = doc.read_display()  # placement="scene_graph_v1", colors="materials_xml"
s = display.summary
print(s.document.writer, s.document.mount_path, s.configurations.selection)
for body in s.bodies:
    buffers = display.body_buffers(body.index)  # positions <f4 (N, 3), triangles <u4 (T, 3), edges <u4 (E, 2)
instances = display.instance_buffers()  # matrices <f8 (N, 16), bodies <u4, colors <u1 (N, 4), face_visibility <u1, visibility <u1, names <u4
preview = display.preview()  # (bytes, media type) or None
```

Placements follow the stored segment tree, modelling matrices, includes and
in-place repeat instances. They are estimates, reported by
`edrawings.display_placement_estimated` and `hsf.placement_estimated`; the
result is never `complete` while unresolved state remains. `placement="verified"`
keeps the fail-closed behaviour and returns no instances in that case. Matrices
use HSF's row-vector convention in source units; nothing is converted. Segments
under the Include Library render only through their includes, and relative
paths that climb above the file root resolve through the mount path recorded in
the first header (`document.mount_path`).

One saved configuration is shown: `configuration=` (a `config name` or a `configN`
segment), else the file's active configuration, else the first. eDrawings marks
the active (current) configuration by leaving its `configN` segment visible and
writing a face-visibility-off record on every other one, so re-saving after
`ShowConfiguration` moves that marker; `configurations.active_node_id` and each
candidate's `hidden` report it, and `selection` is `active` when the marker
exists. Only the shown configuration's subtree is traversed (hsf-core
`Traversal::Subtree`, reported by `hsf.traversal_subtree`), so an
eleven-configuration assembly costs one configuration's instances; the other
candidates are listed in `configurations.candidates` with an instance count of 0.
Each candidate's `display_state` is the `current` (else `default`) state named in
its `displaystates` segment, and `display_states` lists every saved `dispN` state
with its `name` option, `current`/`default` flags and the number of visibility
entries. `display_state=` (a `dispN` segment or a state name) applies another
state of the shown configuration; `configurations.shown_display_state` and
`display_state_selection` (`explicit`, `current`, `default` or `none`) report
which one was applied, and an unknown request fails with
`display.display_state_unknown`. Unicode Options that
eDrawings 2026 writes as sign-extended UTF-8 bytes (`ピン` stored as
U+FFE3 U+FF83 U+FF94 …) are recovered to the intended text in parsed option
values; the raw records keep their stored code units. Colours are per
instance: the inherited HSF colour, then the `materials.xml` entity matching the
body's segment path, then a component's `defaultcolor` option (`colors="hsf_only"`
keeps only the first). Names come from the component chain before the include:
component text, `mbd_comp_name` or `name` options and User Index Data `name`
entries (HOOPS Exchange based writers such as eDrawings 2026), with consecutive
repeats collapsed; names stored inside the included subtree become
`DisplayBody.name` (`Body 0`), and an instance without a component name takes
the body name, else the including segment. `document.model_name` is the
`model_root` name and `document.model_units` the writer's millimetres per model
unit (`1` mm, `1000` m, `25.4` inch) when the option is present; SOLIDWORKS
writers omit it and store metres. `face_visibility` reports the stored HSF face
flag (0 off, 1 on, 2 unset); `visibility` is what eDrawings shows (1 shown, 0
hidden). A component is hidden by default when its segment carries that flag off
(eDrawings writes `defaultvisibility=off` beside it), and the shown display
state's `compN` entries (`path=<segment path>,vis=on|off`) override the default
for the named component and everything below it. Hidden instances are left out of
the buffers unless `include_hidden=True`; `statistics.hidden_instances` and
`hidden_bodies` count them and `edrawings.display_hidden_components` names the
display state. The per-component `showbits0`/`showbits1` words are not
interpreted (they are not needed for visibility). In eDrawings the document-level words on `annotviews` only drive its annotation-category display filter (bit 0 = master, bits 10/2/34/55 = dimension categories 1–4), so they do not affect geometry visibility either. Bodies without an instance, skipped line-only
meshes, a stopped record, unparsed bytes and the colour sources are reported in
`statistics` and `diagnostics`. `read_scene()` and `read_drawing()` also accept
`placement=`.

## Source references and resource limits

`source_bytes(span)` returns the original bytes in the specified decompressed
domain. Container offsets and offsets within internally decompressed data use
different coordinate systems; do not add them together.

`Limits.desktop()` and `Limits.service()` set budgets for input, decompression,
output, records, nodes, and other resources. You can also set individual limits
with `Limits(max_file_bytes=..., max_output_bytes=...)`.
These are parser consumption budgets, not limits on the process's total RSS.
JSON serialization and array copies in your application require additional memory.
