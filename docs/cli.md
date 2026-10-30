# CLI reference

English | [日本語](ja/cli.md)

After installation, `edrawings-kit` and `python -m edrawings_kit` provide the same
interface. Successful results are written to stdout as UTF-8 JSON. Commands do not
modify the input or access the network.

| Command | Result |
| --- | --- |
| `info` | Rust and backend versions, contract version, actual source hash, and capabilities. |
| `probe PATH` | Format identification based on file contents. |
| `inspect PATH` | Container and entry listing. CRC verification and HSF parsing are separate operations. |
| `extract PATH --entry ID --output DEST` | Extract the selected entry to `DEST`, without overwriting an existing file. |
| `verify PATH` | CRC and SHA-256 verification for all entries. |
| `hsf-header PATH [--entry ID]` | HSF header. |
| `hsf PATH [--entry ID]` | HSF syntax parsing with resource limits. |
| `scene PATH [--entry ID]` | Stored elements of a generic scene. |
| `drawing PATH [--entry ID]` | Document and drawing inventories, with semantic support status. |
| `display PATH [--entry ID]` | Display bundle summary: bodies, estimated instances, configurations and colour sources. Buffers are available through the Python API only. |

Use the `raw:0` or `entry:N` IDs returned by `inspect`. When multiple eModel entries
are ambiguous, the CLI requires an explicit selection.

Commands that accept `PATH` also accept `--limits desktop|service`, defaulting to
`desktop`. The `hsf`, `scene`, and `drawing` commands accept:

- `--mode partial|strict` (default: `partial`)
- `--user-data-profile disabled|edrawings_first_be_v2|edrawings_be_envelope_v1` (default: `disabled`)
- `--image-profile disabled|edrawings_1910_u32_v1` (default: `disabled`)

For `scene`, `drawing` and `display`, `--import-root` supplies an explicit absolute
segment context for inventory purposes, and `--placement verified|scene_graph_v1`
selects verified or estimated placements (`display` defaults to `scene_graph_v1`
and to the eDrawings profiles). `display` also accepts
`--colors materials_xml|hsf_only`, `--configuration NAME`, `--display-state NAME` and `--include-hidden` (keep components eDrawings hides, with `visibility` 0).

| Exit code | stdout / stderr |
| --- | --- |
| 0 | Result JSON on stdout. Results may be partial or unsupported; check each stage's status. |
| 2: parser or I/O error | No stdout; `{"error": {"code": ..., ...}}` on stderr. |
| 2: argument error | argparse usage and explanation on stderr, not JSON. |
| 0: `--help` | Usage on stdout, not JSON. |

Unsupported features in strict mode, corruption, and resource limit violations are
errors. Use `error.code` for programmatic handling rather than matching error
messages. JSON output is UTF-8, including when redirected or run under a legacy
Windows code page.

The JSON schema may change between 0.x releases. Record the
output of `info` and the version used alongside your results.
