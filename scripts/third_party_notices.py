"""Collect exact Cargo dependency license texts for the distribution candidate."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

from release_metadata import ROOT, read_toml

OUTPUT = "python/edrawings_kit/_licenses"


def collect(root: Path) -> dict[str, bytes]:
    metadata = json.loads(
        subprocess.check_output(
            ["cargo", "metadata", "--locked", "--format-version", "1"], cwd=root
        )
    )
    locked = {
        (p["name"], p["version"], p.get("source")): p
        for p in read_toml(root / "Cargo.lock")["package"]
    }
    backend = next(p for p in metadata["packages"] if p["name"] == "hsf-core")
    backend_root = Path(backend["manifest_path"]).parent
    files = {
        "NOTICE": (root / "NOTICE").read_bytes(),
        "LICENSE": (root / "LICENSE").read_bytes(),
        "hsf-core-NOTICE": (backend_root / "NOTICE").read_bytes(),
        "hsf-core-LICENSE": (backend_root / "LICENSE").read_bytes(),
    }
    entries = []
    lines = [
        "Third-party Rust dependency notices",
        "",
        "Includes the locked dependency graph across targets and build tools;",
        "this is a conservative inventory, not a claim that every crate is linked.",
        "License expressions and full notices are reproduced from crate distributions.",
        "",
    ]
    for package in sorted(
        metadata["packages"], key=lambda p: (p["name"], p["version"])
    ):
        if package["source"] is None:
            continue
        key = (package["name"], package["version"], package["source"])
        checksum = locked[key].get("checksum")
        if not checksum or not package["license"]:
            raise ValueError(f"Missing checksum or license metadata: {key}")
        source = Path(package["manifest_path"]).parent
        texts = sorted(
            p
            for p in source.iterdir()
            if p.is_file()
            and p.name.upper().startswith(("LICENSE", "COPYING", "NOTICE"))
        )
        if not texts:
            raise ValueError(f"Missing full license text: {key}")
        item = {
            "name": package["name"],
            "version": package["version"],
            "source": package["source"],
            "crate_sha256": checksum,
            "license_expression": package["license"],
            "files": [],
        }
        lines += [f"{package['name']} {package['version']}: {package['license']}"]
        for text in texts:
            name = f"{package['name']}-{package['version']}/{text.name}"
            content = text.read_bytes()
            files[name] = content
            item["files"].append(
                {"path": name, "sha256": hashlib.sha256(content).hexdigest()}
            )
            lines.append("  " + name)
        entries.append(item)
    files["manifest.json"] = (
        json.dumps({"schema_version": 1, "packages": entries}, indent=2) + "\n"
    ).encode()
    files["THIRD_PARTY_NOTICES.txt"] = ("\n".join(lines) + "\n").encode()
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    files = collect(args.root)
    destination = args.root / OUTPUT
    actual = {
        p.relative_to(destination).as_posix(): p.read_bytes()
        for p in destination.rglob("*")
        if p.is_file()
    }
    if args.write:
        for stale in actual.keys() - files.keys():
            (destination / stale).unlink()
        for name, content in files.items():
            path = destination / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
    elif actual != files:
        raise ValueError(
            "Dependency notices are stale; run scripts/third_party_notices.py --write"
        )
    print(
        f"Verified {len(json.loads(files['manifest.json'])['packages'])} "
        "dependency license inventories"
    )


if __name__ == "__main__":
    main()
