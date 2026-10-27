"""Independently verify the authored DXF using raw group-code pairs.

This validates fixture-v2/v3/v4 profiles, not a general DXF parser and not
proof that eDrawings opens, renders, measures or preserves any entity.
No ezdxf or edrawings-kit import is used.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def one(tags, code):
    values = [v for c, v in tags if c == code]
    require(len(values) == 1, f"Expected one group {code}, got {values!r}")
    return values[0]


def scalar(tags, code):
    value = float(one(tags, code))
    require(math.isfinite(value), f"Non-finite group {code}")
    return value


def point(tags, base):
    return [scalar(tags, base + delta) for delta in (0, 10, 20)]


def near(actual, expected, message):
    if isinstance(actual, list):
        require(len(actual) == len(expected), message)
        for a, e in zip(actual, expected, strict=True):
            near(a, e, message)
    else:
        require(math.isclose(actual, expected, rel_tol=0, abs_tol=1e-9), message)


def subclass(tags, name):
    starts = [i for i, item in enumerate(tags) if item == (100, name)]
    require(len(starts) == 1, f"Missing or duplicate subclass {name}")
    start = starts[0] + 1
    end = next((i for i in range(start, len(tags)) if tags[i][0] == 100), len(tags))
    return tags[start:end]


def raw_records(data):
    lines = data.decode("utf-8").splitlines()
    require(len(lines) % 2 == 0, "Incomplete DXF tag pair")
    pairs = [(int(lines[i]), lines[i + 1]) for i in range(0, len(lines), 2)]
    require(pairs[-1] == (0, "EOF"), "Missing DXF EOF")
    records = []
    current = []
    for tag in pairs:
        if tag[0] == 0 and current:
            records.append(current)
            current = []
        current.append(tag)
    if current:
        records.append(current)
    return pairs, records


def verify(manifest_path):
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    require(
        manifest["schema_version"] in (2, 3, 4), "Expected fixture-v2/v3/v4 manifest"
    )
    path = Path(manifest["path"])
    if not path.is_absolute():
        path = manifest_path.parent / path
    data = path.read_bytes()
    require(
        hashlib.sha256(data).hexdigest() == manifest["sha256"], "Fixture hash mismatch"
    )
    pairs, records = raw_records(data)
    for variable, expected in [("$ACADVER", "AC1024"), ("$INSUNITS", "4")]:
        positions = [i for i, p in enumerate(pairs) if p == (9, variable)]
        require(len(positions) == 1, f"Missing/duplicate {variable}")
        require(pairs[positions[0] + 1][1] == expected, f"Incorrect {variable}")
    layout_nodes = [r for r in records if r[0] == (0, "LAYOUT")]
    owners = {}
    layout_names = []
    for record in layout_nodes:
        layout = subclass(record, "AcDbLayout")
        name = one(layout, 1)
        owner = one(layout, 330)
        require(owner not in owners, "Duplicate layout block record")
        owners[owner] = name
        layout_names.append(name)
        if name in manifest["paper_sizes_mm"]:
            settings = subclass(record, "AcDbPlotSettings")
            require(one(settings, 72) == "1", "Paper units are not mm")
            near(
                [scalar(settings, 44), scalar(settings, 45)],
                manifest["paper_sizes_mm"][name],
                "Paper size mismatch",
            )
    require(layout_names == manifest["layouts"], "Layout list mismatch")
    entities = {name: [] for name in layout_names}
    for record in records:
        if (100, "AcDbEntity") not in record:
            continue
        owner = one(record, 330)
        if owner in owners:
            entities[owners[owner]].append(record)
    viewports = []
    for name, expected in manifest["viewports"].items():
        candidates = [
            r for r in entities[name] if r[0] == (0, "VIEWPORT") and one(r, 69) != "1"
        ]
        require(len(candidates) == 1, "Expected one model viewport per layout")
        vp = candidates[0]
        near(point(vp, 10)[:2], expected["center"], "Viewport paper center mismatch")
        near(
            [scalar(vp, 40), scalar(vp, 41)], expected["size"], "Viewport size mismatch"
        )
        near(
            [scalar(vp, 12), scalar(vp, 22)],
            expected["model_center"],
            "View center mismatch",
        )
        near(scalar(vp, 45), expected["model_height"], "View height mismatch")
        near(point(vp, 16), [0, 0, 1], "Fixture requires top orthographic view")
        near(scalar(vp, 51), 0, "Fixture requires no view twist")
        require(one(vp, 90) == "0", "Unexpected viewport flags")
        scale = scalar(vp, 41) / scalar(vp, 45)
        near(scale, expected["scale"], "Viewport scale mismatch")
        # Independently calculated, unclipped top-view coordinates in paper mm.
        projected = [
            [
                expected["center"][i] + scale * (p[i] - expected["model_center"][i])
                for i in range(2)
            ]
            for p in [(0, 0), (100, 0), (100, 50), (0, 50)]
        ]
        viewports.append(
            {
                "layout": name,
                "handle": one(vp, 5),
                "scale": scale,
                "rectangle_paper_points_mm": projected,
            }
        )
    dimensions = []
    for case in manifest["dimension_cases"]:
        selected = [r for r in entities[case["layout"]] if one(r, 8) == case["layer"]]
        if case["entity"] == "DIMENSION":
            candidates = [r for r in selected if r[0] == (0, "DIMENSION")]
            require(len(candidates) == 1, "Expected one source dimension")
            dim = candidates[0]
            require(int(one(dim, 70)) & 15 == 0, "Expected linear dimension")
            near(scalar(dim, 50), 0, "Expected horizontal dimension")
            p1, p2 = point(dim, 13), point(dim, 14)
            near(p1[1:], p2[1:], "Expected horizontal definition points")
            measurement = abs(p2[0] - p1[0])
            near(measurement, case["measurement_mm"], "Actual dimension mismatch")
            require(
                one(dim, 1) == case["display_override"], "Display override mismatch"
            )
            dimensions.append(
                {
                    "layout": case["layout"],
                    "handle": one(dim, 5),
                    "measurement_mm": measurement,
                    "display_override": one(dim, 1),
                    "picture_block": one(dim, 2),
                }
            )
        else:
            require(
                sorted(r[0][1] for r in selected) == ["LINE", "TEXT"],
                "Plain graphics must not contain a DIMENSION",
            )
            line = next(r for r in selected if r[0][1] == "LINE")
            text = next(r for r in selected if r[0][1] == "TEXT")
            near(
                math.dist(point(line, 10), point(line, 11)),
                case["line_length_mm"],
                "Plain line length mismatch",
            )
            require(one(text, 1) == case["text"], "Plain numeric text mismatch")
    model = entities["Model"]
    rectangle = next(r for r in model if r[0][1] == "LWPOLYLINE")
    require(
        one(rectangle, 90) == "4" and int(one(rectangle, 70)) & 1,
        "Rectangle is not closed",
    )
    near(
        [float(v) for c, v in rectangle if c == 10],
        [0, 100, 100, 0],
        "Rectangle X mismatch",
    )
    near(
        [float(v) for c, v in rectangle if c == 20],
        [0, 0, 50, 50],
        "Rectangle Y mismatch",
    )
    circle = next(r for r in model if r[0][1] == "CIRCLE")
    near(point(circle, 10), [50, 25, 0], "Circle center mismatch")
    near(
        scalar(circle, 40), manifest["model_circle_radius_mm"], "Circle radius mismatch"
    )
    jp = manifest["japanese"]
    texts = [
        r
        for r in entities[jp["layout"]]
        if r[0][1] == "TEXT" and one(r, 8) == "M4_JAPANESE"
    ]
    require(len(texts) == 1, "Expected one Japanese label")
    text = texts[0]
    require(one(text, 1) == jp["text"], "Japanese text mismatch")
    near(point(text, 10), jp["insert"], "Japanese placement mismatch")
    near(scalar(text, 40), jp["height"], "Japanese text height mismatch")
    require(one(text, 7) == jp["style"], "Japanese style mismatch")
    styles = [r for r in records if r[0][1] == "STYLE" and one(r, 2) == jp["style"]]
    require(len(styles) == 1, "Missing/duplicate Japanese style")
    style = styles[0]
    require(one(style, 3) == jp["requested_font"], "Requested font mismatch")
    font_extension_verified = manifest["schema_version"] >= 4
    if font_extension_verified:
        starts = [i for i, tag in enumerate(style) if tag == (1001, "ACAD")]
        require(len(starts) == 1, "Missing/duplicate extended font data")
        start = starts[0] + 1
        end = next(
            (i for i in range(start, len(style)) if style[i][0] == 1001), len(style)
        )
        require(
            style[start:end]
            == [
                (1000, jp["extended_font_family"]),
                (1071, str(jp["extended_font_flags"])),
            ],
            "Extended font data mismatch",
        )
    display_contract_verified = manifest["schema_version"] >= 3
    if display_contract_verified:
        display = manifest["display_contract"]
        layers = [r for r in records if r[0] == (0, "LAYER")]
        require(len({one(r, 2) for r in layers}) == len(layers), "Duplicate layer name")
        for name, expected_color in display["layer_colors"].items():
            layer = next((r for r in layers if one(r, 2) == name), None)
            require(layer is not None, f"Missing layer {name}")
            require(int(one(layer, 62)) == expected_color, "Layer color mismatch")
            require(not any(c == 420 for c, _ in layer), "Unexpected layer true color")
        dimstyle = next(
            r
            for r in records
            if r[0] == (0, "DIMSTYLE") and one(r, 2) == display["dimension_style"]
        )
        near(scalar(dimstyle, 144), display["dimension_factor"], "DIMLFAC mismatch")
        positions = [i for i, p in enumerate(pairs) if p == (9, "$DIMLFAC")]
        require(len(positions) == 1, "Missing/duplicate $DIMLFAC")
        near(
            float(pairs[positions[0] + 1][1]),
            display["dimension_factor"],
            "Header DIMLFAC mismatch",
        )
        for dimension in dimensions:
            dim = next(
                r
                for r in records
                if r[0] == (0, "DIMENSION") and one(r, 5) == dimension["handle"]
            )
            require(
                one(dim, 3) == display["dimension_style"], "Dimension style mismatch"
            )
            # This fixture uses only DIMTXT/DIMASZ/DIMDEC overrides. Reject a
            # factor override instead of silently checking the base style only.
            xdata = [i for i, tag in enumerate(dim) if tag == (1000, "DSTYLE")]
            for start in xdata:
                require(dim[start + 1] == (1002, "{"), "Malformed DSTYLE")
                i = start + 2
                while i < len(dim) and dim[i] != (1002, "}"):
                    require(
                        i + 1 < len(dim) and dim[i][0] == 1070,
                        "Malformed DSTYLE override",
                    )
                    require(int(dim[i][1]) != 144, "Unexpected DIMLFAC override")
                    i += 2
                require(i < len(dim), "Unclosed DSTYLE")
            blocks = [
                r
                for r in records
                if r[0] == (0, "BLOCK_RECORD")
                and one(r, 2) == dimension["picture_block"]
            ]
            require(len(blocks) == 1, "Missing/duplicate dimension block")
            owner = one(blocks[0], 5)
            picture = [
                r for r in records if r[0] == (0, "MTEXT") and one(r, 330) == owner
            ]
            require(len(picture) == 1, "Expected one dimension picture text")
            require(not any(c == 3 for c, _ in picture[0]), "Unexpected text chunks")
            require(
                one(picture[0], 1)
                == display["dimension_picture_text"][dimension["layout"]],
                "Dimension picture text mismatch",
            )
    return {
        "source_fixture_verified": True,
        "file_sha256": manifest["sha256"],
        "layouts": layout_names,
        "viewports": viewports,
        "dimensions": dimensions,
        "japanese_text": jp["text"],
        "display_contract_verified": display_contract_verified,
        "font_extension_verified": font_extension_verified,
        "native_reader_verified": False,
        "dimension_semantics_in_saved_edrw_verified": False,
        "scope": (
            "Raw DXF tags only. No native output, font resolution "
            "or EDRW semantics proof."
        ),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = json.dumps(verify(args.manifest), ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x") as output:
            output.write(result)
    print(result, end="")


if __name__ == "__main__":
    main()
