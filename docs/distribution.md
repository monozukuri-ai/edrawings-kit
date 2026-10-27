# 配布物のビルドと検査

Python配布物は、ネイティブ拡張を含むwheelと、ソースからbuildするためのsdistです。
hsf-coreはcrates.ioの固定版に依存し、そのchecksumをCargo.lockで管理します。
sdistのbuildにはRust/Python依存を取得できる環境が必要です。兄弟checkoutは不要です。

## ビルド

開発環境を[開発ガイド](development.md)に従って準備してください。
出力先は以前の配布物を含まないdirectoryを使用します。

```bash
uv run --no-sync python scripts/check_backend.py
uv run --no-sync python scripts/release_metadata.py
uv run --no-sync python scripts/third_party_notices.py
uv run --no-sync python scripts/check_public_tree.py
uv run --no-sync maturin build --release --out dist
uv run --no-sync maturin sdist --out dist
```

Linux向けの配布wheelは互換性を明示してbuildします。

```bash
uv run --no-sync maturin build --release --compatibility manylinux_2_34 --out dist
```

macOS arm64では`MACOSX_DEPLOYMENT_TARGET=11.0`を設定します。
対象OS、architecture、Python版は[対応環境](support.md)を参照してください。

## 検査

```bash
uv run --no-sync python scripts/verify_artifacts.py dist/*.whl --sdist dist/*.tar.gz
```

検査では以下を確認します。

- version、ABIタグ、依存情報、wheelのRECORD hash、型情報。
- LICENSE/NOTICEと依存ライセンス原文、禁止同梱物。
- checkout外の新規venvでのimport、API、console/module両CLI。
- sdistの展開後、crates.io backendのidentityと単独wheel再build・再install。

`.internal`、調査コーパス、検証結果、vendor実行物、fontは同梱しません。
自作の回帰fixtureは、公開テストに必要な入力と期待値だけを収録し、CAD原本のSHA-256を検査します。

CIは3 OSで配布物をbuild・検査し、CPython3.10で生成した同じwheelを他の対象Pythonでも検査します。
これらのスクリプトとCIは、registryやGitHub Releaseへの公開操作を行いません。

参考: [maturinの配布方法](https://www.maturin.rs/distribution.html)、
[Cargoの依存指定](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html)。
