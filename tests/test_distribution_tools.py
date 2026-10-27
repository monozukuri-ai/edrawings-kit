"""Distribution gates must reject stale identity, corruption and unsafe archives."""

import base64
import csv
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import check_backend  # noqa: E402
import check_public_tree  # noqa: E402
import release_metadata  # noqa: E402
import verify_artifacts  # noqa: E402


def test_source_hash_uses_case_sensitive_component_order_on_every_os(tmp_path):
    content = {
        "Cargo.toml": b"manifest",
        "build.rs": b"build",
        "src/A.rs": b"upper",
        "src/a.rs": b"lower",
        "src/scene/primitive.rs": b"nested",
        "src/scene.rs": b"flat",
    }
    # Avoid two paths that collide on Windows; mixed-case root names still test
    # the Cargo.toml/build.rs ordering which failed on the first Windows run.
    del content["src/a.rs"]
    for name, value in content.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    expected = hashlib.sha256(
        b"".join(
            name.encode() + b"\0" + value + b"\0" for name, value in content.items()
        )
    ).hexdigest()
    assert check_backend.fingerprint(tmp_path) == expected


@pytest.mark.parametrize(
    "rust,python",
    [
        ("1.2.3", "1.2.3"),
        ("0.1.0-alpha.1", "0.1.0a1"),
        ("1.2.3-beta.2", "1.2.3b2"),
        ("1.2.3-rc.0", "1.2.3rc0"),
    ],
)
def test_version_mapping(rust, python):
    assert release_metadata.python_version(rust) == python


@pytest.mark.parametrize(
    "value", ["v1.2.3", "01.2.3", "1.2", "1.2.3-alpha", "1.2.3-alpha.01", "1.2.3+local"]
)
def test_version_mapping_rejects_ambiguous_forms(value):
    with pytest.raises(ValueError):
        release_metadata.python_version(value)


@pytest.fixture
def version_root(tmp_path):
    for name in (
        "Cargo.toml",
        "Cargo.lock",
        "pyproject.toml",
        "uv.lock",
        "hsf-backend.lock.json",
        "crates/edrawings-core/Cargo.toml",
        "crates/edrawings-python/Cargo.toml",
    ):
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    return tmp_path


def test_versions_and_tag_agree(version_root):
    result = release_metadata.verify(version_root)
    assert release_metadata.verify(version_root, "v" + result["rust_version"]) == result
    with pytest.raises(ValueError, match="Tag"):
        release_metadata.verify(version_root, "v9.8.7")


def test_stale_cargo_lock_is_rejected(version_root):
    path = version_root / "Cargo.lock"
    current = release_metadata.verify(version_root)["rust_version"]
    content = path.read_text()
    target = f'name = "edrawings-core"\nversion = "{current}"'
    assert content.count(target) == 1
    path.write_text(
        content.replace(target, 'name = "edrawings-core"\nversion = "999.0.0"')
    )
    with pytest.raises(ValueError, match="Stale Cargo.lock"):
        release_metadata.verify(version_root)


def test_stale_backend_version_is_rejected(version_root):
    path = version_root / "hsf-backend.lock.json"
    data = json.loads(path.read_text())
    data["version"] = "999.0.0"
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="exactly match"):
        release_metadata.verify(version_root)


@pytest.mark.parametrize(
    "override", ['path = "../hsf-core"', 'git = "https://example.com/hsf-core"']
)
def test_backend_local_or_git_override_is_rejected(version_root, override):
    path = version_root / "Cargo.toml"
    version = release_metadata.verify(version_root)["backend"]["version"]
    original = f'hsf-core = {{ version = "={version}" }}'
    content = path.read_text()
    assert content.count(original) == 1
    path.write_text(
        content.replace(
            original, f'hsf-core = {{ version = "={version}", {override} }}'
        )
    )
    with pytest.raises(ValueError, match="exactly match"):
        release_metadata.verify(version_root)


def test_backend_checksum_mismatch_is_rejected(version_root):
    path = version_root / "hsf-backend.lock.json"
    data = json.loads(path.read_text())
    data["crate_checksum"] = "0" * 64
    path.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="Cargo.lock"):
        release_metadata.verify(version_root)


@pytest.mark.parametrize("source", [None, "git+https://example.com/hsf-core"])
def test_resolved_backend_must_be_from_registry(monkeypatch, source):
    metadata = {"packages": [{"name": "hsf-core", "source": source}]}
    monkeypatch.setattr(
        check_backend.subprocess, "check_output", lambda args: json.dumps(metadata)
    )
    with pytest.raises(ValueError, match="crates.io"):
        check_backend.registry_backend()


@pytest.mark.parametrize(
    "path",
    ["docs/investigation.md", "scripts/local_probe.py", ".internal/results.json"],
)
def test_public_tree_rejects_internal_files(path):
    with pytest.raises((ValueError, RuntimeError)):
        check_public_tree.check_path(path)


@pytest.mark.parametrize(
    "text",
    [
        "[results](.internal/results.json)",
        "[missing](missing.md)",
        "Local path: /home/developer/private",
    ],
)
def test_public_documentation_rejects_private_or_broken_references(tmp_path, text):
    (tmp_path / "README.md").write_text(text)
    (tmp_path / "LICENSE").write_text("License")
    (tmp_path / "NOTICE").write_text("Notice")
    private = tmp_path / ".internal"
    private.mkdir()
    (private / "results.json").write_text("{}")
    with pytest.raises(ValueError):
        check_public_tree.verify(tmp_path)


@pytest.mark.parametrize(
    "names",
    [
        ["../outside"],
        ["/etc/passwd"],
        ["C:/file"],
        ["a\\..\\file"],
        ["a", "A"],
        ["reports/private.txt"],
        ["project/.internal/results.json"],
        ["project/vendor/hsf-core.tar.gz"],
        ["research/corpus.eprt"],
        ["edrawings_kit/font.ttf"],
        ["arbitrary.dxf"],
    ],
)
def test_artifact_members_fail_closed(names):
    with pytest.raises(RuntimeError):
        verify_artifacts.check_names(names, self_authored_fixtures=True)


def test_authored_cad_fixture_exception_is_sdist_only():
    version = release_metadata.verify()["python_version"]
    name = f"edrawings_kit-{version}/tests/fixtures/native-m4/two-layouts-mm.edrw"
    verify_artifacts.check_names([name], self_authored_fixtures=True)
    with pytest.raises(RuntimeError, match="Corpus"):
        verify_artifacts.check_names([name])


def test_cli_redirected_unicode_is_utf8(tmp_path):
    path = tmp_path / "日本語.hsf"
    path.write_bytes(b";; HSF V19.10 \n\xfe\0")
    result = subprocess.run(
        [sys.executable, "-m", "edrawings_kit", "inspect", str(path)],
        capture_output=True,
        env={**os.environ, "PYTHONIOENCODING": "ascii"},
    )
    assert result.returncode == 0, result.stderr
    assert "日本語" in result.stdout.decode("utf-8")
    json.loads(result.stdout)


@pytest.mark.parametrize("mutation", ["version", "license", "notice", "record"])
def test_wheel_audit_rejects_corrupted_candidate(tmp_path, mutation):
    version = release_metadata.verify()["python_version"]
    dist = f"edrawings_kit-{version}.dist-info"
    files = {
        "edrawings_kit/py.typed": b"",
        "edrawings_kit/_core.pyi": b"# test stub\n",
        "edrawings_kit/_core.abi3.so": b"test extension",
        f"{dist}/METADATA": (
            f"Metadata-Version: 2.4\nName: edrawings-kit\nVersion: {version}\n"
            "Requires-Python: >=3.10\nLicense-Expression: Apache-2.0\n"
        ).encode(),
        f"{dist}/WHEEL": b"Wheel-Version: 1.0\nTag: cp310-abi3-manylinux_2_34_x86_64\n",
    }
    for name in ("LICENSE", "NOTICE"):
        files[f"{dist}/licenses/{name}"] = (ROOT / name).read_bytes()
    for p in (ROOT / "python/edrawings_kit/_licenses").rglob("*"):
        if p.is_file():
            files[p.relative_to(ROOT / "python").as_posix()] = p.read_bytes()
    record = io.StringIO(newline="")
    writer = csv.writer(record)
    for name, content in files.items():
        digest = (
            base64.urlsafe_b64encode(hashlib.sha256(content).digest())
            .rstrip(b"=")
            .decode()
        )
        writer.writerow([name, "sha256=" + digest, len(content)])
    writer.writerow([f"{dist}/RECORD", "", ""])
    files[f"{dist}/RECORD"] = record.getvalue().encode()
    wheel = tmp_path / "candidate.whl"

    def write():
        with zipfile.ZipFile(wheel, "w") as archive:
            for name, content in files.items():
                archive.writestr(name, content)

    write()
    verify_artifacts.audit_wheel(wheel)
    if mutation == "version":
        files[f"{dist}/METADATA"] = files[f"{dist}/METADATA"].replace(
            f"Version: {version}".encode(), b"Version: 999.0.0"
        )
    elif mutation == "license":
        files[f"{dist}/METADATA"] = files[f"{dist}/METADATA"].replace(
            b"Apache-2.0", b"MIT"
        )
    elif mutation == "notice":
        files["edrawings_kit/_licenses/NOTICE"] = b"changed"
    else:
        files["edrawings_kit/_core.abi3.so"] += b"corrupt"
    write()
    with pytest.raises(RuntimeError, match="mismatch"):
        verify_artifacts.audit_wheel(wheel)
