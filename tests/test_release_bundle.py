"""Publication must reuse the complete, verified CI bundle without extra files."""

import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import prepare_release as release  # noqa: E402


@pytest.fixture
def candidates(tmp_path, monkeypatch):
    # Wheel internals are covered by the real artifact audit tests. Here the
    # focus is report binding, selecting all platforms, and transfer integrity.
    monkeypatch.setattr(release, "audit_wheel", lambda path: None)
    identity = release.verify()
    wheels, sdist = release.artifact_names(identity)
    downloads = tmp_path / "candidate"
    for runner, name in wheels.items():
        artifact = downloads / f"wheels-{runner}-python-3.10"
        dist = artifact / "dist"
        dist.mkdir(parents=True)
        wheel = dist / name
        wheel.write_bytes(runner.encode())
        source = dist / sdist
        source.write_bytes((runner + " source archive").encode())
        report = {
            "identity": identity,
            "wheel": name,
            "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
            "sdist_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "python": "3.10.19",
            "cold_install": "passed",
            "sdist_rebuild": "passed",
        }
        path = artifact / ".internal/ci/artifacts.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps(report))
    return downloads


def test_selects_three_wheels_and_linux_sdist_without_reports(candidates, tmp_path):
    bundle = tmp_path / "bundle"
    release.prepare(candidates, bundle)
    release.verify_bundle(bundle)
    wheels, sdist = release.artifact_names(release.verify())
    assert {p.name for p in (bundle / "dist").iterdir()} == {*wheels.values(), sdist}
    assert (bundle / "dist" / sdist).read_bytes() == b"ubuntu-22.04 source archive"
    assert {p.name for p in bundle.iterdir()} == {"dist", "SHA256SUMS"}
    with pytest.raises(ValueError, match="empty"):
        release.prepare(candidates, bundle)


@pytest.mark.parametrize(
    "mutation",
    [
        "wheel",
        "sdist",
        "extra",
        "identity",
        "cold_install",
        "sdist_rebuild",
        "python",
        "wheel_name",
    ],
)
def test_rejects_stale_incomplete_or_changed_ci_artifacts(
    candidates, tmp_path, mutation
):
    artifact = candidates / "wheels-windows-2022-python-3.10"
    dist = artifact / "dist"
    report_path = artifact / ".internal/ci/artifacts.json"
    report = json.loads(report_path.read_text())
    if mutation == "wheel":
        next(dist.glob("*.whl")).write_bytes(b"changed")
    elif mutation == "sdist":
        next(dist.glob("*.tar.gz")).write_bytes(b"changed")
    elif mutation == "extra":
        (dist / "private.json").write_text("{}")
    elif mutation == "wheel_name":
        report["wheel"] = "different.whl"
    elif mutation == "identity":
        report["identity"]["backend"]["source_sha256"] = "0" * 64
    else:
        report[mutation] = "not_passed"
    report_path.write_text(json.dumps(report))
    with pytest.raises(ValueError):
        release.prepare(candidates, tmp_path / "bundle")
    assert not (tmp_path / "bundle").exists()


def test_missing_platform_is_rejected(candidates, tmp_path):
    next((candidates / "wheels-macos-14-python-3.10/dist").glob("*.whl")).unlink()
    with pytest.raises(ValueError, match="inventory"):
        release.prepare(candidates, tmp_path / "bundle")


@pytest.mark.parametrize(
    "mutation", ["bytes", "missing", "extra", "duplicate", "path", "report"]
)
def test_transfer_rejects_changed_bundle(candidates, tmp_path, mutation):
    bundle = tmp_path / "bundle"
    release.prepare(candidates, bundle)
    sums = bundle / "SHA256SUMS"
    if mutation == "bytes":
        next((bundle / "dist").glob("*.whl")).write_bytes(b"changed")
    elif mutation == "missing":
        next((bundle / "dist").glob("*.whl")).unlink()
    elif mutation == "extra":
        (bundle / "dist/extra.whl").write_bytes(b"extra")
    elif mutation == "duplicate":
        sums.write_text(sums.read_text() * 2)
    elif mutation == "path":
        sums.write_text("0" * 64 + "  ../outside\n")
    else:
        (bundle / "private-report.json").write_text("{}")
    with pytest.raises(ValueError):
        release.verify_bundle(bundle)
