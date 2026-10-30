"""Self-authored eDrawings 2026 fixtures: units, axes, names and completeness.

The STEP sources are generated (OCCT box) or project-owned (reference assembly),
so bounds, unit factors and names are known independently of the kit.
"""

import struct
from pathlib import Path

import edrawings_kit as ed
import pytest

FIXTURES = Path(__file__).parent / "fixtures/native-display"


def unpack(buffer):
    code = {"<f4": "f", "<f8": "d", "<i4": "i", "<u4": "I", "<u1": "B"}[buffer.dtype]
    size = struct.calcsize(code)
    flat = struct.unpack(f"<{len(buffer.data) // size}{code}", buffer.data)
    if len(buffer.shape) == 2:
        return tuple(zip(*[iter(flat)] * buffer.shape[1], strict=True))
    return flat


def world_bounds(display):
    instances = display.instance_buffers()
    matrices = unpack(instances.matrices)
    bodies = unpack(instances.bodies)
    low = [float("inf")] * 3
    high = [float("-inf")] * 3
    positions = {}
    for m, body in zip(matrices, bodies, strict=True):
        if body not in positions:
            positions[body] = unpack(display.body_buffers(body).positions)
        for x, y, z in positions[body]:
            point = (
                x * m[0] + y * m[4] + z * m[8] + m[12],
                x * m[1] + y * m[5] + z * m[9] + m[13],
                x * m[2] + y * m[6] + z * m[10] + m[14],
            )
            for k in range(3):
                low[k] = min(low[k], point[k])
                high[k] = max(high[k], point[k])
    return tuple(low), tuple(high)


def instance_names(display):
    summary = display.summary
    instances = display.instance_buffers()
    names = [summary.names[i] for i in unpack(instances.names)]
    paths = [summary.component_paths[i] for i in unpack(instances.component_paths)]
    return names, paths


def complete(display):
    codes = {d.code for d in display.summary.diagnostics}
    assert "edrawings.display_syntax_stopped" not in codes
    assert "edrawings.display_stopped" not in codes
    assert "hsf.unknown_opcode" not in codes
    assert display.summary.statistics.unparsed_bytes == 0
    assert display.summary.statistics.stopped_record_id is None
    assert display.summary.statistics.unplaced_bodies == 0


@pytest.mark.parametrize(
    "name,units,high",
    [
        ("box-100x50x20mm.eprt", 1.0, (100.0, 50.0, 20.0)),
        ("box-100x50x20mm-as-m.eprt", 1000.0, (0.1, 0.05, 0.02)),
        ("box-100x50x20mm-as-inch.eprt", 25.4, (3.937, 1.9685, 0.7874)),
    ],
)
def test_box_keeps_model_units_and_axes(name, units, high):
    display = ed.read_file(FIXTURES / name).read_display()
    s = display.summary
    complete(display)
    assert s.document.hsf_version == "19.10"
    assert s.document.writer is not None
    assert s.document.writer.startswith("HoopsExchange Reader AddIn")
    assert s.document.mount_path == "/include library/model_1_include"
    assert s.document.model_name == Path(name).stem
    assert s.document.model_units == units
    # Six faces, each its own shell, all inside the one included body.
    assert len(s.bodies) == 6
    assert s.instance_count == 6
    assert {b.name for b in s.bodies} == {"Body 0"}
    assert s.statistics.triangles == 12
    low, top = world_bounds(display)
    assert low == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    assert top == pytest.approx(high, abs=1e-3)
    names, paths = instance_names(display)
    assert set(names) == {"Body 0"}
    assert set(paths) == {""}
    assert s.configurations.selection == "none"
    assert display.preview() is not None


def test_reference_assembly_names_placements_and_units():
    display = ed.read_file(FIXTURES / "reference-assembly.easm").read_display()
    s = display.summary
    complete(display)
    assert s.document.model_name == "reference-assembly"
    assert s.document.model_units == 1.0
    assert s.configurations.selection == "first"
    assert len(s.configurations.candidates) == 1
    # Plate: six shells; pin: three shells shared by two placed occurrences.
    assert len(s.bodies) == 9
    assert s.instance_count == 12
    assert s.statistics.triangles == 516
    assert sorted(b.name for b in s.bodies) == ["Body 0"] * 6 + ["Body 1"] * 3
    low, top = world_bounds(display)
    assert low == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    assert top == pytest.approx((40.0, 20.0, 12.0), abs=1e-6)
    names, paths = instance_names(display)
    assert sorted(set(names)) == ["Base Plate", "Pin"]
    assert names.count("Pin") == 6
    assert names.count("Base Plate") == 6
    assert sorted(set(paths)) == ["Base Plate", "Pin Pair/Pin"]
    # Pins sit on the plate at x = 10 and x = 30 (the STEP placements).
    instances = display.instance_buffers()
    matrices = unpack(instances.matrices)
    pin_x = sorted(
        {round(m[12], 6) for m, n in zip(matrices, names, strict=True) if n == "Pin"}
    )
    assert pin_x == [10.0, 30.0]


def test_japanese_names_are_recovered_from_every_record_kind():
    display = ed.read_file(FIXTURES / "japanese-names-assembly.easm").read_display()
    s = display.summary
    complete(display)
    assert s.document.model_name == "japanese-names-assembly"
    assert s.document.model_units == 1.0
    assert len(s.bodies) == 9
    assert s.instance_count == 12
    names, paths = instance_names(display)
    # `name` index entries are UTF-8; the occurrence level's Unicode Options are
    # sign-extended UTF-8 and are repaired, so the chain collapses to one name.
    assert sorted(set(names)) == ["ピン_φ4", "ベース板"]
    assert sorted(set(paths)) == ["ピン_φ4", "ベース板"]
    assert names.count("ピン_φ4") == 6
    assert sorted(b.name for b in s.bodies) == ["Body 0"] * 6 + ["Body 1"] * 3
    low, top = world_bounds(display)
    assert low == pytest.approx((0.0, 0.0, 0.0), abs=1e-6)
    assert top == pytest.approx((40.0, 20.0, 12.0), abs=1e-6)
    # Raw records keep the stored code units: the repair is applied to parsed values.
    scene = ed.read_file(FIXTURES / "japanese-names-assembly.easm").read_scene(
        user_data_profile="edrawings_be_envelope_v1",
        image_profile="edrawings_1910_u32_v1",
    )
    raw = [
        u.text.value
        for u in scene.summary.user_options
        if u.text.encoding == "utf_16_le" and u.text.value and "name=" in u.text.value
    ]
    assert raw and all("\uffe3" in v for v in raw)


def test_fixture_digests_are_pinned():
    import hashlib
    import importlib
    import sys

    scripts = str(Path(__file__).resolve().parents[1] / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    module = importlib.import_module("verify_artifacts")
    for path in sorted(FIXTURES.iterdir()):
        if path.suffix == ".md":
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert module.SELF_AUTHORED_DISPLAY[path.name] == digest
        assert (
            module.fixture_digest(f"x/tests/fixtures/native-display/{path.name}")
            == digest
        )
