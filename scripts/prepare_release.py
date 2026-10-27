"""Collect verified CI artifacts for publication, or verify a transferred bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
from pathlib import Path

from release_metadata import verify
from verify_artifacts import audit_wheel

PLATFORMS = {
    "ubuntu-22.04": "manylinux_2_34_x86_64",
    "windows-2022": "win_amd64",
    "macos-14": "macosx_11_0_arm64",
}


def artifact_names(identity: dict) -> tuple[dict[str, str], str]:
    prefix = "edrawings_kit-" + identity["python_version"]
    wheels = {
        runner: f"{prefix}-cp310-abi3-{platform}.whl"
        for runner, platform in PLATFORMS.items()
    }
    return wheels, prefix + ".tar.gz"


def digest(path: Path) -> str:
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"Expected a regular distribution file: {path}")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(downloads: Path, output: Path) -> None:
    identity = verify()
    wheels, sdist_name = artifact_names(identity)
    selected = []
    for runner, wheel_name in wheels.items():
        artifact = downloads / f"wheels-{runner}-python-3.10"
        dist = artifact / "dist"
        if {p.name for p in dist.iterdir()} != {wheel_name, sdist_name}:
            raise ValueError(f"Unexpected CI distribution inventory: {runner}")
        report = json.loads(
            (artifact / ".internal/ci/artifacts.json").read_text(encoding="utf-8")
        )
        if (
            report.get("identity") != identity
            or report.get("cold_install") != "passed"
            or report.get("sdist_rebuild") != "passed"
            or not report.get("python", "").startswith("3.10.")
            or report.get("wheel") != wheel_name
        ):
            raise ValueError(f"CI verification identity or status mismatch: {runner}")
        wheel, sdist = dist / wheel_name, dist / sdist_name
        if digest(wheel) != report.get("wheel_sha256") or digest(sdist) != report.get(
            "sdist_sha256"
        ):
            raise ValueError(f"CI artifact digest mismatch: {runner}")
        audit_wheel(wheel)
        selected.append(wheel)
        # Each OS rebuilds its own sdist in CI. Publish the Linux source archive;
        # compressor timestamps or host details need not produce identical bytes.
        if runner == "ubuntu-22.04":
            selected.append(sdist)
    if output.exists() and any(output.iterdir()):
        raise ValueError("Release bundle output must be empty")
    dist = output / "dist"
    dist.mkdir(parents=True)
    lines = []
    for source in sorted(selected, key=lambda p: p.name):
        destination = dist / source.name
        shutil.copyfile(source, destination)
        lines.append(f"{digest(destination)}  {destination.name}\n")
    (output / "SHA256SUMS").write_text("".join(lines), encoding="ascii")


def verify_bundle(bundle: Path) -> None:
    wheels, sdist_name = artifact_names(verify())
    expected = {*wheels.values(), sdist_name}
    if {p.name for p in bundle.iterdir()} != {"dist", "SHA256SUMS"}:
        raise ValueError("Unexpected release bundle contents")
    if {p.name for p in (bundle / "dist").iterdir()} != expected:
        raise ValueError("Unexpected release distribution inventory")
    checksums = {}
    for line in (bundle / "SHA256SUMS").read_text(encoding="ascii").splitlines():
        match = re.fullmatch(r"([a-f0-9]{64})  ([A-Za-z0-9_.-]+)", line)
        if not match or match[2] in checksums:
            raise ValueError("Invalid or duplicate release checksum entry")
        checksums[match[2]] = match[1]
    if checksums.keys() != expected:
        raise ValueError("Release checksum inventory mismatch")
    for name, checksum in checksums.items():
        path = bundle / "dist" / name
        if digest(path) != checksum:
            raise ValueError(f"Release distribution digest mismatch: {name}")
        if name.endswith(".whl"):
            audit_wheel(path)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    collect = actions.add_parser("collect")
    collect.add_argument("downloads", type=Path)
    collect.add_argument("output", type=Path)
    check = actions.add_parser("verify")
    check.add_argument("bundle", type=Path)
    args = parser.parse_args()
    if args.action == "collect":
        prepare(args.downloads, args.output)
        print(f"Prepared 3 wheels, 1 sdist and SHA256SUMS in {args.output}")
    else:
        verify_bundle(args.bundle)
        print("Release bundle inventory, hashes and wheel metadata verified")


if __name__ == "__main__":
    main()
