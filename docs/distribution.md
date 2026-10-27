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
same wheel built with CPython 3.10 on other supported Python versions. These
scripts and CI do not publish to registries or GitHub Releases.

References: [maturin distribution guide](https://www.maturin.rs/distribution.html),
[Cargo dependency specification](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html).
