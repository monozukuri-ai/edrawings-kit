# edrawings-kit

English | [日本語](README.ja.md)

A Rust core and Python bindings for reading eDrawings files (`.eprt`, `.easm`, and
`.edrw`). Extract container contents, supported HSF geometry, text and attributes,
and stored document structure, with diagnostics and source references.
HSF parsing uses [hsf-core](https://crates.io/crates/hsf-core).
The eDrawings application and HOOPS SDK are not required at runtime.

This is a read-only parser with limited format support. It does not provide
complete placement or rendering for arbitrary files, reconstruct editable CAD
models or dimension definitions, or write CAD files. Read the
[support and limitations guide](docs/support.md) and check the status and
diagnostics returned by each operation.

## Installation

Use CPython 3.10 or later. Rust is not required when installing a compatible wheel.
Replace the path below with the wheel for your platform:

```bash
python -m pip install "/path/to/edrawings_kit-<version>-<platform>.whl"
```

Installing from source requires Rust 1.88 or later:

```bash
git clone https://github.com/monozukuri-ai/edrawings-kit.git
cd edrawings-kit
python -m pip install .
```

Cargo downloads hsf-core from crates.io. A separate repository checkout is not required.

## Python

```python
import edrawings_kit as ed

info = ed.inspect_file("part.eprt")
for entry in info.entries:
    print(entry.id, entry.name, entry.bytes, entry.crc_status)

doc = ed.read_file("part.eprt", limits=ed.Limits.desktop())
parsed = doc.parse_hsf(mode="partial")
print(parsed.summary.stages.hsf_syntax)
for diagnostic in parsed.summary.diagnostics:
    print(diagnostic.code, diagnostic.message)
```

`inspect_file()` lists entries. CRC verification and HSF parsing are separate
operations. In `partial` mode, parsing returns the supported prefix when it reaches
an unsupported feature, so a successful call does not necessarily mean parsing is
complete. `strict` mode raises an exception for unsupported features. Corruption
and resource limit violations raise exceptions in both modes.

To parse product-specific User Data in supported files, explicitly select an
experimental profile:

```python
drawing = doc.read_drawing(user_data_profile="edrawings_be_envelope_v1")
print(drawing.summary.sheet_inventory)
print(drawing.summary.component_inventory)
print(drawing.summary.assessment.status)
```

This profile also does not guarantee complete rendering or placement. Unknown
information and original bytes are preserved. See the [Python API guide](docs/api.md)
for geometry buffers, text, source references, and error handling.

## CLI

```bash
edrawings-kit info
edrawings-kit inspect part.eprt
edrawings-kit scene part.eprt --mode partial
edrawings-kit drawing drawing.edrw --user-data-profile edrawings_be_envelope_v1
edrawings-kit verify part.eprt --limits service
edrawings-kit extract part.eprt --entry entry:0 --output model.hsf
```

Results are UTF-8 JSON. Extraction requires an explicit destination and does not
overwrite existing files. See the [CLI reference](docs/cli.md) for commands,
options, and exit codes.

## Documentation

- [Python API guide](docs/api.md)
- [Supported platforms, formats, and limitations](docs/support.md)
- [Development and testing](docs/development.md)
- [Building and verifying distributions](docs/distribution.md)

## License

[Apache-2.0](LICENSE). Dependency license texts and attribution notices are bundled.
See [NOTICE](NOTICE) for details.
