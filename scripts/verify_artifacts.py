"""Audit and cold-install a wheel; optionally rebuild an sdist with no sibling repo."""

from __future__ import annotations

import argparse
import base64
import csv
import email.parser
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path, PurePosixPath

from check_backend import backend_identity
from release_metadata import verify

ROOT = Path(__file__).resolve().parents[1]

# Project-authored native regression artifacts are intentionally shipped only
# in the sdist. Third-party research corpus files remain forbidden everywhere.
SELF_AUTHORED_EDRW = {
    "two-layouts-mm.dxf": (
        "9700d98bd95f9e443b141edc14a9e481f00ee15de420ce08cc906094da7e68c8"
    ),
    "two-layouts-visible-mm.dxf": (
        "bc6fcf3cbf6b64647d786c3ffe8dfb34ce223e54e1562d7b76452cf5cc49a601"
    ),
    "two-layouts-japanese-mm.dxf": (
        "244ef91343e7daef6089a879eb3943816f2f864455bc29210e07b1ea191111f4"
    ),
    "two-layouts-mm.edrw": (
        "d601dbac0130f4084800ab3cdbeb5e15d4ce8f7992a3c360b0b8d6936fc70632"
    ),
    "two-layouts-visible-mm.edrw": (
        "8c730618130c26dbe628e0aa3767e4d3a220444e76556c4cf49f475f1f52ca11"
    ),
    "two-layouts-japanese-mm.edrw": (
        "3de42bf9aa6424678e3e919562573dfe89593f1ce878efde733ca4bc89516fc1"
    ),
}

# Self-authored EPRT/EASM written by eDrawings 2026 from STEP files the project
# generated (OCCT box) or owns (cad3d-ir-step reference assembly). Units and
# axes are known from the STEP sources, so these are the display oracles.
SELF_AUTHORED_DISPLAY = {
    "box-100x50x20mm.step": (
        "3deb6b35f5ad1fa989632d45e7031a60c54f66e25375cd4ebca098e1f859de18"
    ),
    "box-100x50x20mm.eprt": (
        "463b1ec21b0fe6083a93b7b3bd7b3921fb70e989f0972da219d238d2dbe686be"
    ),
    "box-100x50x20mm-as-m.step": (
        "f0018cf4ab5c76ef1326ffb7f936e9440d9be96acd68534b61b6fb38a54a0127"
    ),
    "box-100x50x20mm-as-m.eprt": (
        "e916b99c9b9219a40ed0e48ab0f44ece977cb8ec58454b0830646c0d57989b06"
    ),
    "box-100x50x20mm-as-inch.step": (
        "50dde32bbf722f7635eaf855616a5856ccfe6e3782520b056fd6c1de2e5531d6"
    ),
    "box-100x50x20mm-as-inch.eprt": (
        "089e78d01965e30d1a7c471552cde789a9443eeff3c4271e9f1de713b9b8175f"
    ),
    "reference-assembly.step": (
        "ce52a8347e020edfde44305023aa882f465adb2c621b33651cb8fa5da4d8e76b"
    ),
    "reference-assembly.easm": (
        "41c86cdbcc1b204c0278c2f070daa42cd61a055118718d2ec1f48f155a3b5d0a"
    ),
    "japanese-names-assembly.step": (
        "460d9be9353ea8550700bf93c23309f646557ce5134f73c3d8183ef29c44158e"
    ),
    "japanese-names-assembly.easm": (
        "c79b0e902e66dbd685d1770ecf58c791782e09286b6bd870e342b45b0e7568fe"
    ),
}

SELF_AUTHORED = {
    "native-m4": SELF_AUTHORED_EDRW,
    "native-display": SELF_AUTHORED_DISPLAY,
}


def fixture_digest(name: str) -> str | None:
    parts = PurePosixPath(name).parts
    if len(parts) == 5 and parts[1:3] == ("tests", "fixtures"):
        return SELF_AUTHORED.get(parts[3], {}).get(parts[-1])
    return None


def run(command: list[str], cwd: Path) -> None:
    subprocess.run(command, cwd=cwd, check=True)


def check_names(names: list[str], *, self_authored_fixtures: bool = False) -> None:
    if len({name.casefold() for name in names}) != len(names):
        raise RuntimeError("Duplicate or case-colliding artifact members")
    for name in names:
        path = PurePosixPath(name)
        parts = path.parts
        if path.is_absolute() or ".." in parts or "\\" in name or ":" in name:
            raise RuntimeError(f"Unsafe artifact member: {name}")
        if any(
            p in parts
            for p in (
                ".internal",
                "research",
                "reports",
                "vendor",
                ".venv",
                ".git",
                "target",
                "__pycache__",
            )
        ):
            raise RuntimeError(f"Unexpected artifact member: {name}")
        if path.suffix.lower() in (".ttf", ".otf", ".exe", ".dll"):
            raise RuntimeError(f"Unexpected vendor executable or font: {name}")
        if path.suffix.lower() in (
            ".eprt",
            ".easm",
            ".edrw",
            ".hsf",
            ".dxf",
            ".dwg",
            ".step",
            ".stp",
        ):
            if self_authored_fixtures and fixture_digest(name):
                continue
            raise RuntimeError(f"Corpus file leaked into artifact: {name}")


def audit_wheel(wheel: Path) -> None:
    expected = verify()
    with zipfile.ZipFile(wheel) as archive:
        names = archive.namelist()
        check_names(names)
        assert "edrawings_kit/py.typed" in names
        assert "edrawings_kit/_core.pyi" in names
        assert any(name.endswith((".so", ".pyd")) for name in names)
        metadata = email.parser.BytesParser().parsebytes(
            archive.read(next(n for n in names if n.endswith(".dist-info/METADATA")))
        )
        if (
            metadata["Name"] != "edrawings-kit"
            or metadata["Version"] != expected["python_version"]
            or metadata["Requires-Python"] != ">=3.10"
            or metadata.get_all("Requires-Dist")
            or metadata["License-Expression"] != "Apache-2.0"
        ):
            raise RuntimeError("Wheel version or dependency metadata mismatch")
        info_root = next(
            n.rsplit("/", 1)[0] for n in names if n.endswith(".dist-info/METADATA")
        )
        for name in ("LICENSE", "NOTICE"):
            if (
                archive.read(f"{info_root}/licenses/{name}")
                != (ROOT / name).read_bytes()
            ):
                raise RuntimeError(f"Wheel project {name} mismatch")
        wheel_metadata = email.parser.BytesParser().parsebytes(
            archive.read(next(n for n in names if n.endswith(".dist-info/WHEEL")))
        )
        if not all(
            tag.startswith("cp310-abi3-") for tag in wheel_metadata.get_all("Tag", [])
        ) or not wheel_metadata.get_all("Tag"):
            raise RuntimeError("Wheel must use cp310-abi3")
        notice_root = ROOT / "python/edrawings_kit/_licenses"
        expected_notices = {
            "edrawings_kit/_licenses/"
            + p.relative_to(notice_root).as_posix(): p.read_bytes()
            for p in notice_root.rglob("*")
            if p.is_file()
        }
        if (
            not expected_notices
            or {
                n
                for n in names
                if n.startswith("edrawings_kit/_licenses/") and not n.endswith("/")
            }
            != expected_notices.keys()
        ):
            raise RuntimeError("Wheel NOTICE inventory mismatch")
        for name, content in expected_notices.items():
            if archive.read(name) != content:
                raise RuntimeError(f"Wheel NOTICE content mismatch: {name}")
        record_name = next(n for n in names if n.endswith(".dist-info/RECORD"))
        rows = list(csv.reader(io.StringIO(archive.read(record_name).decode())))
        if len(rows) != len(names) or {r[0] for r in rows} != set(names):
            raise RuntimeError("Wheel RECORD inventory mismatch")
        for name, digest, size in rows:
            if name == record_name:
                continue
            content = archive.read(name)
            actual = (
                "sha256="
                + base64.urlsafe_b64encode(hashlib.sha256(content).digest())
                .rstrip(b"=")
                .decode()
            )
            if digest != actual or size != str(len(content)):
                raise RuntimeError(f"Wheel RECORD digest mismatch: {name}")


def install(wheel: Path, directory: Path) -> None:
    audit_wheel(wheel)
    run(["uv", "venv", "--python", sys.executable, str(directory / "venv")], directory)
    python = (
        directory / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    )
    run(
        ["uv", "pip", "install", "--python", str(python), "--no-deps", str(wheel)],
        directory,
    )
    smoke = directory / "verify_install.py"
    shutil.copyfile(ROOT / "scripts/verify_install.py", smoke)
    expected = verify()
    run(
        [
            str(python),
            "-I",
            str(smoke),
            expected["backend"]["source_sha256"],
            expected["python_version"],
            expected["rust_version"],
        ],
        directory,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("wheel", type=Path)
    parser.add_argument("--sdist", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    wheel = args.wheel.resolve()
    with tempfile.TemporaryDirectory(prefix="edrawings-artifacts-") as temp:
        root = Path(temp)
        cold = root / "cold"
        cold.mkdir()
        install(wheel, cold)
        if args.sdist:
            unpack = root / "unpack"
            unpack.mkdir()
            with tarfile.open(args.sdist.resolve()) as archive:
                check_names(archive.getnames(), self_authored_fixtures=True)
                if len(set(archive.getnames())) != len(archive.getnames()):
                    raise RuntimeError("Duplicate sdist member")
                for member in archive.getmembers():
                    path = PurePosixPath(member.name)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or not (member.isfile() or member.isdir())
                    ):
                        raise RuntimeError(f"Unsafe sdist member: {member.name}")
                    expected = fixture_digest(member.name)
                    if expected is not None:
                        content = archive.extractfile(member)
                        if (
                            content is None
                            or hashlib.sha256(content.read()).hexdigest() != expected
                        ):
                            raise RuntimeError(
                                f"Self-authored fixture digest mismatch: {member.name}"
                            )
                # All members validated above, including link types.
                archive.extractall(unpack)
            projects = list(unpack.glob("*/pyproject.toml"))
            assert len(projects) == 1
            project = projects[0].parent
            assert not (unpack / "hsf-core").exists()
            if (project / "hsf-core").exists():
                raise RuntimeError("sdist must resolve hsf-core from crates.io")
            if backend_identity(project) != verify()["backend"]:
                raise RuntimeError("sdist registry backend identity mismatch")
            for name in ("LICENSE", "NOTICE"):
                if (project / name).read_bytes() != (ROOT / name).read_bytes():
                    raise RuntimeError(f"sdist project {name} mismatch")
            out = root / "rebuilt"
            # Uses the build frontend from this environment, but only extracted sources.
            run(
                [
                    str(
                        Path(sys.executable).parent
                        / ("maturin.exe" if os.name == "nt" else "maturin")
                    ),
                    "build",
                    "--release",
                    "--out",
                    str(out),
                    "--interpreter",
                    sys.executable,
                ],
                project,
            )
            rebuilt = list(out.glob("*.whl"))
            assert len(rebuilt) == 1
            second = root / "rebuilt-cold"
            second.mkdir()
            install(rebuilt[0], second)
    report = {
        "wheel": wheel.name,
        "wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
        "sdist_sha256": hashlib.sha256(args.sdist.read_bytes()).hexdigest()
        if args.sdist
        else None,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "python": platform.python_version(),
        "identity": verify(),
        "cold_install": "passed",
        "sdist_rebuild": "passed" if args.sdist else "not_requested",
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
