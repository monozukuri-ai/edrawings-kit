# Native display fixtures (eDrawings 2026 writer)

Self-authored EPRT/EASM files saved by eDrawings 2026 (HOOPS Exchange STEP
import, HOOPS 3DF 20.10 stream writer behind a 19.10 header) from STEP sources
that the project generated or owns. No third-party CAD data is included.

| File | Source | Known truth |
| --- | --- | --- |
| `box-100x50x20mm.step` / `.eprt` | OCCT `BRepPrimAPI_MakeBox(100, 50, 20)`, STEP in millimetres | one body, bounds 0–100 × 0–50 × 0–20, `model_units=1.000000` |
| `box-100x50x20mm-as-m.step` / `.eprt` | same box written with `write.step.unit=M` | bounds 0–0.1 × 0–0.05 × 0–0.02, `model_units=1000.000000` |
| `box-100x50x20mm-as-inch.step` / `.eprt` | same box written with `write.step.unit=INCH` | bounds 0–3.937 × 0–1.9685 × 0–0.7874, `model_units=25.400000` |
| `reference-assembly.step` / `.easm` | cad3d-ir-step reference assembly (plate 40 × 20 × 2 with two Ø4 × 10 pins) | three solids, bounds 0–40 × 0–20 × 0–12, `model_units=1.000000` |
| `japanese-names-assembly.step` / `.easm` | the same plate and pins written with XCAF names `ベース板`, `ピン_φ4`, `組立 試験` as Part 21 `\X2\` escapes | component names `ベース板` and `ピン_φ4`; User Index Data `name` entries are UTF-8, Unicode Options carry the UTF-8 bytes sign-extended to 16-bit code units |

What these files establish:

- Coordinates are stored in the model's own units with no axis change; the
  `includes` segment carries `model_units=<millimetres per unit>`.
  SOLIDWORKS-written files do not carry the option and store metres.
- The writer uses TKE_Priority, TKE_User_Index_Data (`name` entries),
  three-word Rendering Options and backquoted segment names, all framed by
  hsf-core 0.1.0-alpha.3.
- Non-ASCII names: `name` index entries and `__step/productname` options are
  UTF-8; `display name` / `name` Unicode Options are the same UTF-8 bytes
  widened by sign extension (`ピ` = e3 83 94 arrives as U+FFE3 U+FF83 U+FF94).
  A STEP whose names are raw UTF-8 without `\X2\` escapes is read by the
  importer in the Windows code page and comes out garbled before writing.

Digests are pinned in `scripts/verify_artifacts.py`; the files ship only in the
sdist, like the `native-m4` fixtures.
