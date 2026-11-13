"""Prepare a release: set the version, follow an hsf-core release, refresh lock files.

Run from the repository root:

    uv run --no-sync python scripts/bump_version.py patch --check
    uv run --no-sync python scripts/bump_version.py 0.3.0 --hsf-core 0.1.0-alpha.8
    uv run --no-sync python scripts/bump_version.py 0.2.6 --hsf-core keep

The first argument is the new version, or ``patch``/``minor`` for the next final
release after the newest ``v*`` tag. ``--hsf-core`` defaults to the newest hsf-core
release on crates.io; ``keep`` leaves the current pin. The script edits
``Cargo.toml``, lets Cargo update ``Cargo.lock``, rewrites ``hsf-backend.lock.json``
and the bundled license inventory, and validates the release metadata. Running it
again with the same arguments changes nothing. ``--check`` then runs the quality
gates from CI. The script never commits, tags or publishes; it prints those commands.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import sysconfig
import urllib.error
import urllib.request
from pathlib import Path

from release_metadata import ROOT, python_version, read_toml, verify

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib

INDEX = "https://index.crates.io/hs/f-/hsf-core"
PYPI = "https://pypi.org/pypi/edrawings-kit/{}/json"
USER_AGENT = "edrawings-kit-release-script (github.com/monozukuri-ai/edrawings-kit)"
SEMVER = re.compile(
    r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
    r"(?:-([0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*))?"
)
VERSION_LINE = re.compile(r'version = "[^"]*"\s*')
BACKEND_LINE = re.compile(r'hsf-core = \{ version = "=[^"]*" \}\s*')


def semver_key(version: str) -> tuple:
    """Sort key with SemVer precedence: 0.1.0-alpha.9 < 0.1.0-alpha.10 < 0.1.0."""
    match = SEMVER.fullmatch(version)
    if not match:
        raise ValueError(f"Not a semantic version: {version}")
    core = tuple(int(part) for part in match.groups()[:3])
    if match[4] is None:
        return (*core, 1, ())
    identifiers = tuple(
        (0, int(part), "") if part.isdigit() else (1, 0, part)
        for part in match[4].split(".")
    )
    return (*core, 0, identifiers)


def released_tags(root: Path = ROOT) -> list[str]:
    """Versions of the ``v*`` tags in the local repository."""
    try:
        output = subprocess.check_output(
            ["git", "-C", str(root), "tag", "--list", "v*"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    return [tag[1:] for tag in output.split() if SEMVER.fullmatch(tag[1:]) is not None]


def next_version(current: str, requested: str, tags: list[str]) -> str:
    """Resolve ``patch``/``minor`` against the newest tag, or check an explicit one."""
    if requested in ("patch", "minor"):
        base = max(tags, key=semver_key) if tags else current
        match = SEMVER.fullmatch(base)
        if not match or match[4] is not None:
            raise ValueError(f"Give the version explicitly after the prerelease {base}")
        major, minor, patch = (int(part) for part in match.groups()[:3])
        if requested == "patch":
            requested = f"{major}.{minor}.{patch + 1}"
        else:
            requested = f"{major}.{minor + 1}.0"
    python_version(requested)
    if semver_key(requested) < semver_key(current):
        raise ValueError(f"{requested} is older than the current version {current}")
    return requested


def edit_manifest(text: str, version: str, backend: str) -> str:
    """Set ``workspace.package.version`` and the exact hsf-core requirement."""
    lines = text.splitlines(keepends=True)
    section = None
    found = set()
    for index, line in enumerate(lines):
        header = re.fullmatch(r"\[([^\]]+)\]\s*", line)
        if header:
            section = header[1]
        elif section == "workspace.package" and VERSION_LINE.fullmatch(line):
            lines[index] = f'version = "{version}"\n'
            found.add("version")
        elif section == "workspace.dependencies" and BACKEND_LINE.fullmatch(line):
            lines[index] = f'hsf-core = {{ version = "={backend}" }}\n'
            found.add("hsf-core")
    if found != {"version", "hsf-core"}:
        raise ValueError("Cargo.toml lacks the expected version or hsf-core line")
    edited = "".join(lines)
    workspace = tomllib.loads(edited)["workspace"]
    if workspace["package"]["version"] != version or workspace["dependencies"][
        "hsf-core"
    ] != {"version": "=" + backend}:
        raise ValueError("Cargo.toml edit did not produce the requested versions")
    return edited


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


def published_backends() -> dict[str, bool]:
    """hsf-core versions in the crates.io index, mapped to whether they are yanked."""
    lines = fetch(INDEX).decode().splitlines()
    return {
        entry["vers"]: bool(entry["yanked"])
        for entry in map(json.loads, filter(None, lines))
    }


def choose_backend(requested: str, current: str) -> str:
    if requested == "keep":
        return current
    try:
        published = published_backends()
    except (OSError, ValueError) as error:
        if requested == "latest":
            raise SystemExit(
                f"Cannot read the crates.io index ({error}); pass --hsf-core VERSION "
                "or --hsf-core keep"
            ) from None
        print(f"warning: crates.io index unavailable ({error}); Cargo will check")
        return requested
    if requested == "latest":
        candidates = [v for v, yanked in published.items() if not yanked]
        newest = max(candidates, key=semver_key)
        if semver_key(newest) < semver_key(current):
            raise SystemExit(
                f"The newest hsf-core on crates.io ({newest}) is older than {current}"
            )
        return newest
    if requested not in published:
        raise SystemExit(f"hsf-core {requested} is not on crates.io")
    if published[requested]:
        raise SystemExit(f"hsf-core {requested} is yanked")
    return requested


def on_pypi(version: str) -> bool | None:
    """Whether PyPI already has this release; ``None`` when PyPI cannot be reached."""
    try:
        fetch(PYPI.format(python_version(version)))
    except urllib.error.HTTPError as error:
        return False if error.code == 404 else None
    except OSError:
        return None
    return True


def cargo_command(root: Path = ROOT) -> list[str]:
    """Cargo from the toolchain the CI workflow pins, when rustup has it."""
    workflow = (root / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    match = re.search(r"dtolnay/rust-toolchain@([0-9][0-9.]*)", workflow)
    if match and shutil.which("rustup"):
        toolchains = subprocess.run(
            ["rustup", "toolchain", "list"], capture_output=True, text=True
        ).stdout
        if any(line.startswith(match[1] + "-") for line in toolchains.splitlines()):
            return ["cargo", "+" + match[1]]
        print(f"note: Rust {match[1]} (used by CI) is not installed; using cargo")
    return ["cargo"]


def run(command: list[str], env: dict[str, str] | None = None) -> None:
    print("$", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True, env=env)


def python_library_env() -> dict[str, str]:
    """Let Rust test binaries find libpython of an interpreter outside system paths.

    PyO3 builds against the active virtual environment's interpreter. CI's
    setup-python exports its library directory; a uv-managed interpreter does not.
    """
    env = dict(os.environ)
    if sys.platform == "win32":
        key, directory = "PATH", sys.base_prefix
    else:
        key = "DYLD_LIBRARY_PATH" if sys.platform == "darwin" else "LD_LIBRARY_PATH"
        directory = sysconfig.get_config_var("LIBDIR") or ""
    if directory:
        env[key] = os.pathsep.join(filter(None, [directory, env.get(key)]))
    return env


def quality_gates(cargo: list[str]) -> None:
    """The checks of the CI quality and distribution jobs, without building wheels."""
    uv = ["uv", "run", "--no-sync"]
    for command in (
        [*cargo, "fmt", "--all", "--check"],
        [*cargo, "clippy", "--workspace", "--all-targets", "--locked", "--"]
        + ["-D", "warnings"],
        ["uv", "sync", "--frozen", "--group", "dev"],
        [*uv, "python", "scripts/check_backend.py"],
        [*uv, "python", "scripts/release_metadata.py"],
        [*uv, "python", "scripts/third_party_notices.py"],
        [*uv, "ruff", "check", "python", "tests", "scripts"],
        [*uv, "ruff", "format", "--check", "python", "tests", "scripts"],
        [*uv, "mypy"],
        [*uv, "python", "scripts/check_public_tree.py"],
    ):
        run(command)
    run([*cargo, "test", "--workspace", "--locked"], env=python_library_env())
    run([*uv, "pytest", "-q"])


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(__doc__ or "").split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(__doc__ or "").split("\n", 2)[-1],
    )
    parser.add_argument("version", help="new version, or patch / minor")
    parser.add_argument(
        "--hsf-core",
        default="latest",
        metavar="VERSION",
        help="hsf-core release to pin: a version, latest (default) or keep",
    )
    parser.add_argument(
        "--check", action="store_true", help="run the CI quality gates afterwards"
    )
    args = parser.parse_args()

    manifest = ROOT / "Cargo.toml"
    workspace = read_toml(manifest)["workspace"]
    current = workspace["package"]["version"]
    current_backend = workspace["dependencies"]["hsf-core"]["version"].lstrip("=")
    lock = ROOT / "hsf-backend.lock.json"
    before = json.loads(lock.read_text(encoding="utf-8"))
    tags = released_tags()
    try:
        version = next_version(current, args.version, tags)
    except ValueError as error:
        raise SystemExit(str(error)) from None
    if version in tags:
        raise SystemExit(f"Tag v{version} already exists; choose the next version")
    published = on_pypi(version)
    if published:
        raise SystemExit(f"edrawings-kit {version} is already on PyPI")
    if published is None:
        print("warning: PyPI is unreachable; not checked for an existing release")
    backend = choose_backend(args.hsf_core.lstrip("="), current_backend)

    text = manifest.read_text(encoding="utf-8")
    edited = edit_manifest(text, version, backend)
    if edited != text:
        manifest.write_text(edited, encoding="utf-8")
    cargo = cargo_command()
    # Compare with Cargo.lock, not the manifest, so a rerun after a failed update
    # (for example, an index that has not caught up yet) still moves the lock.
    locked = [
        package["version"]
        for package in read_toml(ROOT / "Cargo.lock")["package"]
        if package["name"] == "hsf-core"
    ]
    if locked != [backend]:
        run([*cargo, "update", "hsf-core", "--precise", backend])
    run([*cargo, "update", "--workspace"])
    run([sys.executable, "scripts/check_backend.py", "--update"])
    run([sys.executable, "scripts/third_party_notices.py", "--write"])
    identity = verify()
    after = identity["backend"]

    print()
    print(f"edrawings-kit {current} -> {version} (Python {identity['python_version']})")
    print(f"hsf-core      {before['version']} -> {after['version']}")
    if before["contract_version"] != after["contract_version"]:
        print(
            f"hsf-core contract {before['contract_version']} -> "
            f"{after['contract_version']}: review the hsf-core changelog"
        )
    status = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--short"], capture_output=True, text=True
    ).stdout
    if status:
        print("Changed files:\n" + status.rstrip())

    if args.check:
        try:
            quality_gates(cargo)
        except subprocess.CalledProcessError as error:
            command = " ".join(error.cmd)
            raise SystemExit(f"Check failed: {command}") from None
        print("\nAll local quality gates passed.")
    else:
        print(
            "\nRun the CI quality gates by repeating the command with --check:\n"
            f"  uv run --no-sync python scripts/bump_version.py {version} --check"
        )
    print(
        "\nThen commit and tag; the Release workflow publishes after the full CI:\n"
        "  git add -A\n"
        f'  git commit -m "Release {version}"\n'
        "  git push origin HEAD\n"
        f"  git tag v{version}\n"
        f"  git push origin v{version}"
    )


if __name__ == "__main__":
    main()
