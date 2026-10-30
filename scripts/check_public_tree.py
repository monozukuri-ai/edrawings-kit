"""Check public documentation, paths and fixtures before building a distribution."""

from __future__ import annotations

import argparse
import hashlib
import re
import subprocess
from pathlib import Path
from urllib.parse import unquote

from verify_artifacts import SELF_AUTHORED, check_names

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_DOCS = {"api.md", "cli.md", "development.md", "distribution.md", "support.md"}
PUBLIC_DOCS |= {"ja/" + name for name in PUBLIC_DOCS}
PUBLIC_SCRIPTS = {
    "check_backend.py",
    "check_public_tree.py",
    "prepare_release.py",
    "release_metadata.py",
    "third_party_notices.py",
    "verify_artifacts.py",
    "verify_install.py",
}
ROOTS = (".github", "crates", "python", "tests", "scripts", "docs")
GENERATED = {"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "target"}
PRIVATE_TEXT = re.compile(
    r"/home/[^/\s]+/|/Users/[^/\s]+/|[A-Z]:\\Users\\|\bev_[a-f0-9]{32,}\b"
)


def check_path(name: str) -> None:
    path = Path(name)
    if path.parts[0] == "docs" and path.as_posix() not in {
        "docs/" + n for n in PUBLIC_DOCS
    }:
        raise ValueError(f"Non-public documentation: {name}")
    if path.parts[0] == "scripts" and path.as_posix() not in {
        "scripts/" + n for n in PUBLIC_SCRIPTS
    }:
        raise ValueError(f"Non-public script: {name}")
    check_names(["project/" + path.as_posix()], self_authored_fixtures=True)


def verify(root: Path = ROOT) -> int:
    files = [root / "README.md", root / "NOTICE", root / "LICENSE"]
    files.extend(root.glob("README.*.md"))
    for directory in ROOTS:
        files.extend(
            p
            for p in (root / directory).rglob("*")
            if p.is_file()
            and not any(part in GENERATED for part in p.relative_to(root).parts)
            and p.suffix not in {".so", ".pyd", ".pyc"}
        )
    for path in files:
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValueError(f"Public source must not link to local data: {relative}")
        check_path(relative)
        expected_digest = next(
            (
                digests[path.name]
                for directory, digests in SELF_AUTHORED.items()
                if path.name in digests and path.parent.name == directory
            ),
            None,
        )
        if expected_digest is not None:
            if hashlib.sha256(path.read_bytes()).hexdigest() != expected_digest:
                raise ValueError(f"Fixture digest mismatch: {relative}")
        if path.suffix == ".md":
            content = path.read_text(encoding="utf-8")
            if PRIVATE_TEXT.search(content):
                raise ValueError(f"Local paths or runtime evidence in {relative}")
            for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", content):
                target = link.split("#", 1)[0]
                if not target or "://" in target or target.startswith("mailto:"):
                    continue
                destination = (path.parent / unquote(target)).resolve()
                if (
                    not destination.is_relative_to(root.resolve())
                    or ".internal" in destination.parts
                    or not destination.exists()
                ):
                    raise ValueError(
                        f"Broken or private documentation link: {relative}: {target}"
                    )
    if (root / ".git").exists():
        tracked = (
            subprocess.check_output(["git", "-C", str(root), "ls-files", "-z"])
            .decode()
            .split("\0")
        )
        for name in filter(None, tracked):
            check_path(name)
    return len(files)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    print(f"Verified {verify(args.root)} public source files")


if __name__ == "__main__":
    main()
