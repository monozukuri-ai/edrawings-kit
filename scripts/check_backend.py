"""Verify the resolved crates.io backend against the checked-in identity."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

from release_metadata import read_toml

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


def registry_backend(root: Path = ROOT) -> dict:
    metadata = json.loads(
        subprocess.check_output(
            [
                "cargo",
                "metadata",
                "--locked",
                "--format-version",
                "1",
                "--manifest-path",
                str(root / "Cargo.toml"),
            ]
        )
    )
    packages = [p for p in metadata["packages"] if p["name"] == "hsf-core"]
    if len(packages) != 1 or packages[0]["source"] != REGISTRY:
        raise ValueError("hsf-core must resolve to a single crates.io package")
    return packages[0]


def fingerprint(root: Path) -> str:
    files = [root / "Cargo.toml", root / "build.rs", *root.glob("src/**/*.rs")]
    digest = hashlib.sha256()
    # Match Rust's case-sensitive path-component order on every OS.
    for path in sorted(files, key=lambda p: p.relative_to(root).parts):
        digest.update(path.relative_to(root).as_posix().encode() + b"\0")
        digest.update(path.read_bytes() + b"\0")
    return digest.hexdigest()


def backend_identity(root: Path = ROOT) -> dict:
    package = registry_backend(root)
    source = Path(package["manifest_path"]).parent
    locked = [
        p
        for p in read_toml(root / "Cargo.lock")["package"]
        if p["name"] == "hsf-core"
        and p.get("source") == REGISTRY
        and p["version"] == package["version"]
    ]
    if len(locked) != 1:
        raise ValueError("Backend registry entry is missing from Cargo.lock")
    checksum = locked[0]["checksum"]
    contract = re.search(
        r"pub const CONTRACT_VERSION: u32 = (\d+);",
        (source / "src/lib.rs").read_text(encoding="utf-8"),
    )
    if not contract or not checksum:
        raise ValueError("Backend identity is missing")
    return {
        "schema_version": 2,
        "version": package["version"],
        "contract_version": int(contract[1]),
        "source_sha256": fingerprint(source),
        "registry_source": REGISTRY,
        "crate_checksum": checksum,
        "repository": package["repository"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    identity = backend_identity(args.root)
    lock = args.root / "hsf-backend.lock.json"
    if args.update:
        lock.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    elif json.loads(lock.read_text(encoding="utf-8")) != identity:
        raise SystemExit(
            "Backend identity mismatch; review the dependency before --update"
        )
    print(f"HSF registry source verified: {identity['source_sha256']}")


if __name__ == "__main__":
    main()
