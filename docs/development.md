# Development and testing

English | [日本語](ja/development.md)

Use Rust 1.88 or later, CPython 3.10 or later, and [uv](https://docs.astral.sh/uv/).

```bash
uv sync --frozen --group dev
uv run --no-sync python scripts/check_backend.py
uv run --no-sync maturin develop
```

`Cargo.toml` pins hsf-core to a crates.io release. Checks compare the `Cargo.lock`
checksum and the version, contract, and source hash in `hsf-backend.lock.json`, and
reject unexpected path or Git dependencies. A separate hsf-core checkout is not
required.

## Quality checks

```bash
cargo +1.88.0 fmt --all --check
cargo +1.88.0 clippy --workspace --all-targets --locked -- -D warnings
cargo +1.88.0 test --workspace --locked
uv run --no-sync ruff check python tests scripts
uv run --no-sync ruff format --check python tests scripts
uv run --no-sync mypy
uv run --no-sync pytest -q
uv run --no-sync python scripts/check_public_tree.py
```

The regular test suite uses small generated inputs and bundled project-authored
fixtures. It does not download private data or external CAD samples.

## Repository layout

- `crates/edrawings-core`: containers, eDrawings-specific conventions, and the HSF adapter.
- `crates/edrawings-python`: PyO3 bindings.
- `python/edrawings_kit`: typed Python API and CLI.
- `tests`: regression tests, independent reference implementations, and fixtures.
- `scripts`: dependency, version, license, public-tree, and distribution checks.

Generic HSF syntax belongs in hsf-core; eDrawings-specific conventions belong in
this project. Preserve diagnostics and original bytes for unknown syntax,
attributes, and semantics instead of silently reporting success.

## Updating dependencies

When updating hsf-core, update `Cargo.toml` and `Cargo.lock`, review the changes,
and then run:

```bash
uv run --no-sync python scripts/check_backend.py --update
uv run --no-sync python scripts/third_party_notices.py --write
uv run --no-sync maturin develop
uv run --no-sync pytest -q
```

The backend source hash includes the manifest extracted by Cargo. A Git checkout
and a registry package may have different hashes because Cargo normalizes the
manifest.

The version source of truth is `workspace.package.version` in `Cargo.toml`.
Rust version `0.1.0-alpha.1` maps to Python distribution version `0.1.0a1`.
`scripts/release_metadata.py` checks their consistency.

Store research material, execution logs, and local environment details in
`.internal/`, which is excluded from Git and distributions. Keep reproducible tests
and user-facing support information in the public tree.

## Documentation languages

`README.md` and `docs/*.md` are the default English documentation. The Japanese
versions are `README.ja.md` and `docs/ja/*.md`. Keep corresponding pages and code
examples in sync, and retain the language links at the top of each page.
