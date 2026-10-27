# Self-authored drawing fixtures

These files contain project-authored rectangles, circles, lines, dimensions and
text, with two paper layouts and a model layout. They do not contain a third-party
CAD design, fonts or vendor software.

Each DXF has a matching EDRW exported by eDrawings 2026 SP4.1. The three variants
exercise different layer colors, dimension display overrides and Japanese font
metadata. The EDRW hashes are fixed in parser tests and the distribution audit.
The DXF manifests contain input geometry and expected field values for offline
regression tests; they are not native application execution reports.

The original variant intentionally retains unusual display settings. The visible
variant changes color and dimension display settings. The Japanese variant adds
extended TrueType metadata and contains the UTF-8 label `寸法確認 100 mm` in its EDRW.
Fixture names and sheet names are stable test identifiers.

An offline test of these files verifies parser behavior for these inputs. It does
not establish complete rendering, font selection, dimensions or compatibility
with every eDrawings writer. Do not modify the binary fixtures to update test
expectations; add a separately documented input when extending coverage.
