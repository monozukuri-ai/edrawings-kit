"""Reject the actual color/measurement mistakes found in the native fixture.

The validator reads raw DXF tags; these tests require neither ezdxf nor Wine.
"""

import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests/fixtures/native-m4"
spec = importlib.util.spec_from_file_location(
    "native_fixture_validator", ROOT / "tests/helpers/verify_dxf.py"
)
assert spec is not None and spec.loader is not None
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


def test_corrected_fixture_checks_color_factor_and_generated_picture_text():
    result = validator.verify(FIXTURES / "visible-mm-fixture-manifest.json")
    assert result["display_contract_verified"]
    assert [d["measurement_mm"] for d in result["dimensions"]] == [100, 25.4]
    assert not result["native_reader_verified"]
    assert not result["font_extension_verified"]


def test_original_fixture_is_not_retroactively_display_qualified():
    result = validator.verify(FIXTURES / "fixture-manifest.json")
    assert not result["display_contract_verified"]
    assert not result["font_extension_verified"]


def test_japanese_fixture_preserves_extended_truetype_data():
    result = validator.verify(FIXTURES / "japanese-mm-fixture-manifest.json")
    assert result["display_contract_verified"]
    assert result["font_extension_verified"]
    assert result["japanese_text"] == "寸法確認 100 mm"
    assert not result["native_reader_verified"]


@pytest.mark.parametrize("mutation", ["missing", "family", "flags", "duplicate"])
def test_reject_missing_or_changed_font_extension_after_hash_update(tmp_path, mutation):
    manifest = json.loads(
        (FIXTURES / "japanese-mm-fixture-manifest.json").read_text(encoding="utf-8")
    )
    _, records = validator.raw_records(
        (FIXTURES / "two-layouts-japanese-mm.dxf").read_bytes()
    )
    style = next(r for r in records if r[0] == (0, "STYLE") and (2, "M4_JAPANESE") in r)
    start = style.index((1001, "ACAD"))
    if mutation == "missing":
        del style[start:]
    elif mutation == "family":
        style[style.index((1000, "TakaoPGothic"))] = (1000, "Arial")
    elif mutation == "flags":
        style[style.index((1071, "34"))] = (1071, "0")
    else:
        style.extend(style[start:])
    data = "".join(f"{code}\n{value}\n" for r in records for code, value in r).encode()
    dxf = tmp_path / "mutated.dxf"
    dxf.write_bytes(data)
    manifest.update(path=dxf.name, sha256=hashlib.sha256(data).hexdigest())
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="[Ee]xtended font data"):
        validator.verify(path)


@pytest.mark.parametrize(
    "mutation,expected",
    [
        ("white_layer", "Layer color mismatch"),
        ("factor_100", "DIMLFAC mismatch"),
        ("stale_picture", "Dimension picture text mismatch"),
        ("override_factor", "Unexpected DIMLFAC override"),
    ],
)
def test_reject_regressions_even_when_manifest_hash_is_updated(
    tmp_path, mutation, expected
):
    manifest = json.loads(
        (FIXTURES / "visible-mm-fixture-manifest.json").read_text(encoding="utf-8")
    )
    pairs, records = validator.raw_records(
        (FIXTURES / "two-layouts-visible-mm.dxf").read_bytes()
    )
    del pairs
    if mutation == "white_layer":
        record = next(
            r for r in records if r[0] == (0, "LAYER") and (2, "M4_MODEL") in r
        )
        record[record.index((62, "1"))] = (62, "7")
    elif mutation == "factor_100":
        record = next(
            r for r in records if r[0] == (0, "DIMSTYLE") and (2, "EZDXF") in r
        )
        record[record.index((144, "1.0"))] = (144, "100.0")
    elif mutation == "stale_picture":
        record = next(r for r in records if r[0] == (0, "MTEXT") and (1, "100") in r)
        record[record.index((1, "100"))] = (1, "10000")
    else:
        record = next(r for r in records if r[0] == (0, "DIMENSION"))
        end = record.index((1002, "}"))
        record[end:end] = [(1070, "144"), (1040, "100.0")]
    data = "".join(f"{code}\n{value}\n" for r in records for code, value in r).encode()
    dxf = tmp_path / "mutated.dxf"
    dxf.write_bytes(data)
    manifest.update(path=dxf.name, sha256=hashlib.sha256(data).hexdigest())
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match=expected):
        validator.verify(path)
