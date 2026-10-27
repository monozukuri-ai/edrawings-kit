"""Validate Cargo-owned versions and local distribution metadata."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


def read_toml(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


def python_version(version: str) -> str:
    number = r"(?:0|[1-9][0-9]*)"
    match = re.fullmatch(
        rf"({number}\.{number}\.{number})(?:-(alpha|beta|rc)\.({number}))?", version
    )
    if not match:
        raise ValueError("Supported versions: X.Y.Z or X.Y.Z-(alpha|beta|rc).N")
    suffix = {"alpha": "a", "beta": "b", "rc": "rc"}
    return match[1] + (suffix[match[2]] + match[3] if match[2] else "")


def verify(root: Path = ROOT, tag: str | None = None) -> dict:
    workspace = read_toml(root / "Cargo.toml")["workspace"]
    project = read_toml(root / "pyproject.toml")["project"]
    version = workspace["package"]["version"]
    pep440 = python_version(version)
    if (
        workspace["package"].get("license") != "Apache-2.0"
        or project.get("license") != "Apache-2.0"
    ):
        raise ValueError("Project license metadata must be Apache-2.0")
    if "version" in project or "version" not in project.get("dynamic", []):
        raise ValueError("Python version must be derived from Cargo workspace")
    packages = read_toml(root / "Cargo.lock")["package"]
    for member in workspace["members"]:
        crate = read_toml(root / member / "Cargo.toml")["package"]
        if crate["version"] != {"workspace": True}:
            raise ValueError(f"{member} must inherit the workspace version")
        if crate.get("license") != {"workspace": True}:
            raise ValueError(f"{member} must inherit the workspace license")
        locked = [
            p for p in packages if p["name"] == crate["name"] and "source" not in p
        ]
        if len(locked) != 1 or locked[0]["version"] != version:
            raise ValueError(f"Stale Cargo.lock version for {crate['name']}")
    backend = json.loads((root / "hsf-backend.lock.json").read_text(encoding="utf-8"))
    if workspace["dependencies"]["hsf-core"] != {"version": "=" + backend["version"]}:
        raise ValueError("HSF dependency must exactly match the backend lock")
    locked = [p for p in packages if p["name"] == "hsf-core"]
    if (
        len(locked) != 1
        or locked[0]["version"] != backend["version"]
        or locked[0].get("source") != backend["registry_source"]
        or locked[0].get("checksum") != backend["crate_checksum"]
    ):
        raise ValueError("Stale Cargo.lock version for hsf-core")
    uv = [
        p
        for p in read_toml(root / "uv.lock")["package"]
        if p["name"] == "edrawings-kit"
    ]
    if len(uv) != 1 or uv[0].get("source") != {"editable": "."} or "version" in uv[0]:
        raise ValueError("uv.lock must use dynamic local project metadata")
    if tag is not None and tag != "v" + version:
        raise ValueError(f"Tag must be v{version}")
    return {"rust_version": version, "python_version": pep440, "backend": backend}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--tag")
    args = parser.parse_args()
    print(json.dumps(verify(args.root, args.tag), indent=2))


if __name__ == "__main__":
    main()
