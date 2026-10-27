# 配布物のビルドと検査

[English](../distribution.md) | 日本語

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
通常のCIはパッケージを公開しません。公開は以下のリリースworkflowで行います。

## リリースworkflow

`.github/workflows/release.yml`は`v*`タグのpushで起動します。タグはCargo.tomlの
`v<workspace.package.version>`と完全一致する必要があります。
プレリリースもRustの表記を使用します（例: `v0.1.0-alpha.1`。Python表記の`v0.1.0a1`ではありません）。

メタデータの検証後、再利用可能なCI workflow全体を実行します。
CPython 3.10で生成したLinux x86_64・Windows x86_64・macOS arm64のwheelと、
Linuxで生成したsdistを収集し、CIの検証結果とSHA-256を照合して`publication-bundle` artifactを作成します。
公開jobではこのbundleを再検査して使用し、パッケージを再buildしません。
内部の実行レポートはbundleに含めません。

タグpush時はTrusted PublishingでPyPIへ公開し、続けて同じ4配布物と`SHA256SUMS`を添付した
GitHub Releaseを作成します。プレリリースタグはGitHubでもprereleaseとなり、latestには設定しません。
アップロードの再開時は、既存のGitHub添付物との完全一致を確認します。
公開対象はPython配布物のみで、Rust crateは公開しません。

### 初回設定

GitHubに`pypi` environmentを作成し、以下の値で
[PyPI Trusted Publisher](https://docs.pypi.org/trusted-publishers/adding-a-publisher/)を登録します。

| 設定 | 値 |
| --- | --- |
| PyPI project | `edrawings-kit` |
| GitHub owner | `monozukuri-ai` |
| Repository | `edrawings-kit` |
| Workflow filename | `release.yml` |
| Environment | `pypi` |

PyPIプロジェクトがまだ存在しない場合は、
[pending publisher](https://docs.pypi.org/trusted-publishers/creating-a-project-through-oidc/)を登録します。
PyPI API tokenは不要です。PyPI公開jobのみに`id-token: write`を与え、
別のGitHub Release公開jobに`contents: write`を与えます。

### 検証と公開

workflowの変更をpushした後、手動実行で指定refの検証とbundleの生成を行えます。
手動実行ではPyPI・GitHub Releaseへ公開しません。

```bash
gh workflow run release.yml --ref main
```

公開時はworkspaceのversionとCargo.lockを更新し、リリース変更をcommit・pushします。
そのcommitから対応するタグを作成し、pushしてください。

```bash
tag="$(uv run --no-sync python -c 'from scripts.release_metadata import verify; print("v" + verify()["rust_version"])')"
git tag "$tag"
git push origin "$tag"
```

bundle作成後に失敗した場合は、失敗したjobのみを再実行して元の配布物を再利用します。
既存のPyPIファイルを黙ってスキップする設定にはしていません。
一部のみアップロードされた場合は、公開済みファイルのhashを`SHA256SUMS`と比較してから復旧し、
タグの移動や公開済みバイトの置き換えは行わないでください。

参考: [maturinの配布方法](https://www.maturin.rs/distribution.html)、
[Cargoの依存指定](https://doc.rust-lang.org/cargo/reference/specifying-dependencies.html)。
