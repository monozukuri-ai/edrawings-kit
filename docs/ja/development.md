# 開発とテスト

[English](../development.md) | 日本語

Rust 1.88以上、CPython 3.10以上、[uv](https://docs.astral.sh/uv/)を使用します。

```bash
uv sync --frozen --group dev
uv run --no-sync python scripts/check_backend.py
uv run --no-sync maturin develop
```

hsf-coreはCargo.tomlでcrates.ioの版を固定しています。Cargo.lockのchecksumと
`hsf-backend.lock.json`の版・契約・source hashを検査し、意図しないpath/git依存を拒否します。
別のhsf-core checkoutは不要です。

## 品質チェック

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

通常のテストは生成した小さな入力と同梱の自作fixtureだけで実行できます。
非公開データや外部のCADサンプルをダウンロードしません。

## 構成

- `crates/edrawings-core`: コンテナ、eDrawings固有規約、HSFアダプタ。
- `crates/edrawings-python`: PyO3バインディング。
- `python/edrawings_kit`: 型付きPython APIとCLI。
- `tests`: 回帰試験、独立した参照実装、fixture。
- `scripts`: 依存・version・ライセンス・公開範囲・配布物の検査。

HSFの汎用構文はhsf-coreで扱い、eDrawings固有規約は本プロジェクトで扱います。
未知の構文・属性・意味を黙って成功に変えず、診断と元バイトを保持してください。

## 依存の更新

hsf-coreの更新時はCargo.tomlとCargo.lockを更新し、変更内容を確認してから以下を実行します。

```bash
uv run --no-sync python scripts/check_backend.py --update
uv run --no-sync python scripts/third_party_notices.py --write
uv run --no-sync maturin develop
uv run --no-sync pytest -q
```

backend source hashにはCargoが展開したmanifestも含まれます。
Git checkoutとregistry packageはmanifestの正規化により異なるhashになることがあります。

版の正本はCargo.tomlの`workspace.package.version`です。
正式版はRustとPythonで同じ表記（例: `0.1.0`）を使用します。
プレリリースではRustの`0.2.0-alpha.1`がPython配布の`0.2.0a1`となります。
`scripts/release_metadata.py`で整合性を検査します。

調査資料・実行ログ・個人環境情報は`.internal/`に保存し、Gitや配布物に含めません。
公開側に必要なのは再現可能な試験と利用者向けの対応範囲です。

## ドキュメントの言語

`README.md`と`docs/*.md`はデフォルトの英語版です。
日本語版は`README.ja.md`と`docs/ja/*.md`に配置します。
対応するページとコード例を同期し、各ページ先頭の言語切り替えリンクを維持してください。
