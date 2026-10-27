# Building and verifying distributions

English | [日本語](ja/distribution.md)

Python distributions consist of a wheel containing the native extension and an
sdist for building from source. The project depends on a pinned hsf-core release
from crates.io, with its checksum recorded in `Cargo.lock`. Building an sdist
requires access to Rust and Python dependencies, but no sibling repository
checkout.

## Build

Prepare the environment using the [development guide](development.md).
Use an output directory that does not contain artifacts from earlier builds.

```bash
uv run --no-sync python scripts/check_backend.py
uv run --no-sync python scripts/release_metadata.py
uv run --no-sync python scripts/third_party_notices.py
uv run --no-sync python scripts/check_public_tree.py
uv run --no-sync maturin build --release --out dist
uv run --no-sync maturin sdist --out dist
```

For Linux distribution wheels, specify the compatibility baseline explicitly:

```bash
uv run --no-sync maturin build --release --compatibility manylinux_2_34 --out dist
```

On macOS arm64, set `MACOSX_DEPLOYMENT_TARGET=11.0`. See
[supported platforms](support.md) for target operating systems, architectures, and
Python versions.

## Verify

```bash
uv run --no-sync python scripts/verify_artifacts.py dist/*.whl --sdist dist/*.tar.gz
```

Verification checks:

- Versions, ABI tags, dependency metadata, wheel RECORD hashes, and type information.
- LICENSE/NOTICE files, original dependency license texts, and prohibited contents.
- Imports, API calls, and both console and module CLI entry points in a fresh virtual environment outside the checkout.
- The crates.io backend identity in the extracted sdist, followed by a standalone wheel rebuild and fresh installation.

Distributions exclude `.internal`, research corpora, validation results, vendor
executables, and fonts. Project-authored regression fixtures contain only the
inputs and expected values required for public tests; the original CAD files are
verified by SHA-256.

CI builds and verifies distributions on three operating systems, then tests the
same wheel built with CPython 3.10 on other supported Python versions. The regular
CI workflow does not publish packages; the release workflow below handles publication.

## Release workflow

`.github/workflows/release.yml` runs on `v*` tag pushes. The tag must exactly match
`v<workspace.package.version>` in `Cargo.toml`, including the Rust prerelease suffix
(for example, `v0.1.0-alpha.1`, not the Python spelling `v0.1.0a1`).

The workflow validates metadata, runs the complete reusable CI workflow, and
collects the CPython 3.10 wheels for Linux x86_64, Windows x86_64, and macOS arm64,
plus the Linux-built sdist. It checks the CI reports and SHA-256 digests and creates
a `publication-bundle` artifact. Publication jobs reuse that bundle and recheck it;
they do not rebuild packages. Internal reports are not included in the bundle.

On a tag push, the workflow publishes to PyPI with Trusted Publishing, then
creates a GitHub Release with the same four distributions and `SHA256SUMS`.
Prerelease tags produce GitHub prereleases and are not marked as the latest release.
Existing GitHub assets must match exactly before a failed upload can be resumed.
The workflow publishes Python distributions only; it does not publish Rust crates.

### One-time configuration

Create a GitHub environment named `pypi`. Configure a
[PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)
with these values:

| Setting | Value |
| --- | --- |
| PyPI project | `edrawings-kit` |
| GitHub owner | `monozukuri-ai` |
| Repository | `edrawings-kit` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

If the PyPI project does not exist yet, register a
[pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/).
No PyPI API token is required. The publishing job receives `id-token: write`;
GitHub Release publication receives `contents: write` in its separate job.

### Validate and publish

After pushing the workflow changes, a manual run validates the selected ref and
uploads the bundle without publishing to PyPI or GitHub Releases:

```bash
gh workflow run release.yml --ref main
```

To publish, update the workspace version and `Cargo.lock`, commit and push the
release changes, then create and push the matching tag from that commit:

```bash
tag="$(uv run --no-sync python -c 'from scripts.release_metadata import verify; print("v" + verify()["rust_version"])')"
git tag "$tag"
git push origin "$tag"
```

For a failure after bundle preparation, rerun the failed jobs to reuse the
original artifacts. The workflow does not silently skip existing PyPI files.
If an upload was partial, compare the published file hashes with `SHA256SUMS`
before recovering the release; do not move the tag or replace published bytes.

References: [maturin distribution guide](https://www.maturin.rs/distribution.html),
[Cargo dependency specification](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html).
