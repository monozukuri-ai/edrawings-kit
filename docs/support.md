# Supported platforms, formats, and limitations

English | [日本語](ja/support.md)

## Runtime platforms

| Component | Target |
| --- | --- |
| Python | CPython 3.10–3.14, standard builds with the GIL |
| Linux wheel | x86_64, glibc 2.34 or later |
| Windows wheel | x86_64 |
| macOS wheel | arm64, macOS 11 or later |
| Source build | Rust 1.88 or later, maturin/PyO3 |

Wheels use the `cp310-abi3` tag. CI tests Python 3.10–3.14 on Linux and 3.10 and 3.14
on Windows and macOS. Python 3.11–3.13 on Windows/macOS, free-threaded Python, PyPy,
and other architectures are not qualified.
The parser does not require eDrawings or the HOOPS SDK at runtime.

## Files and data

| Area | Supported scope |
| --- | --- |
| Containers | Raw HSF, standard ZIP, and supported ZIP containers with a 92-byte prefix |
| ZIP | Store/Deflate, entry listings, extraction with resource limits, CRC/SHA-256 |
| HSF | A limited set of 8.05 / 14.50 / 19.10 opcodes, internal zlib compression, source references, and unparsed ranges |
| Geometry | Stored values for supported Shell/Mesh, line, polyline, polygon, circle, and arc records |
| Text | Known encoding conventions, with raw bytes and source references retained |
| Attributes | Stored information for supported colors, visibility, matrices, line styles, fonts, glyphs, and rendering settings |
| Documents | Supported sheets/views, component trees and local transforms, multiple configurations, and limited drawing units |
| Product-specific User Data and images | Explicitly selected experimental profiles only |

ZIP64, split or encrypted ZIP archives, unknown compression methods, and HSF data
or writers outside the supported profiles are not supported. Semantic processing
also remains incomplete for mesh compression, LOD, images/textures, style
references, clipping, and other features. Use `edrawings_kit.build_info()` or
`edrawings-kit info` to inspect the available capabilities.

## Interpreting results

Reading geometry definitions does not necessarily establish world placement or
final appearance. Check `placement_status`, the document `assessment`, each
inventory and attribute status, and diagnostics. The parser does not emit
uncertain placements when unresolved information remains.

The project does not provide support for all eDrawings files, rendering equivalent
to the official viewer, editable B-Rep or modeling history, recovery of original
CAD dimensions, tolerances, or origins, or export to CAD formats. It does not infer
unit or dimension semantics solely from a file extension or stored numeric text.

The API and JSON schema may change between 0.x releases. Record the version and backend identity
from `build_info()`, and check compatibility against your inputs and outputs when
upgrading.
