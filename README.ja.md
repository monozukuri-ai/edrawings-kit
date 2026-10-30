# edrawings-kit

[English](README.md) | 日本語

eDrawings形式（`.eprt` / `.easm` / `.edrw`）を読み取るRustコアとPythonバインディングです。
コンテナ内のデータ、対応するHSFの形状・文字・属性、保存された文書構造を、診断と出典付きで取得します。
HSFの処理には[hsf-core](https://crates.io/crates/hsf-core)を使用します。
eDrawingsアプリやHOOPS SDKは実行時に必要ありません。

対応範囲を限定した読み取り専用パーサです。任意のファイルの完全な形状配置・表示再現、
編集可能なCADモデルや寸法定義の復元、書き出しには対応していません。
[対応範囲](docs/ja/support.md)を確認し、結果のstatusとdiagnosticsを処理してください。

## インストール

CPython 3.10以上を使用します。対応wheelがある場合、Rust環境は不要です。
以下のパスを対象環境のwheelに置き換えてください。

```bash
python -m pip install "/path/to/edrawings_kit-<version>-<platform>.whl"
```

ソースからのインストールにはRust 1.88以上が必要です。

```bash
git clone https://github.com/monozukuri-ai/edrawings-kit.git
cd edrawings-kit
python -m pip install .
```

hsf-coreはcrates.ioから取得します。別のリポジトリのcheckoutは不要です。

## Python

```python
import edrawings_kit as ed

info = ed.inspect_file("part.eprt")
for entry in info.entries:
    print(entry.id, entry.name, entry.bytes, entry.crc_status)

doc = ed.read_file("part.eprt", limits=ed.Limits.desktop())
parsed = doc.parse_hsf(mode="partial")
print(parsed.summary.stages.hsf_syntax)
for diagnostic in parsed.summary.diagnostics:
    print(diagnostic.code, diagnostic.message)
```

`inspect_file()`はentry一覧を取得します。CRC検証やHSF解析は別の操作です。
`partial`は未対応箇所までの結果を返すため、成功した呼び出しでも完全な解析とは限りません。
`strict`は未対応を例外にし、破損や資源制限の超過は両モードで例外にします。

実ファイルの製品固有User Dataを解析する場合は、対応する実験プロファイルを明示します。

```python
drawing = doc.read_drawing(user_data_profile="edrawings_be_envelope_v1")
print(drawing.summary.sheet_inventory)
print(drawing.summary.component_inventory)
print(drawing.summary.assessment.status)
```

このプロファイルも完全な描画や配置を保証しません。未知の情報と元バイトを保持します。
形状バッファ、文字、出典、例外の扱いは[Python APIガイド](docs/ja/api.md)を参照してください。

ビューア向けには`read_display()`が、本体のpacked bufferと保存された1構成分の推定配置を、色と名前付きで返します。

```python
display = doc.read_display()
print(display.summary.instance_count, display.summary.configurations.selection)
instances = display.instance_buffers()  # 行列、本体index、色、名前
```

## CLI

```bash
edrawings-kit info
edrawings-kit inspect part.eprt
edrawings-kit scene part.eprt --mode partial
edrawings-kit drawing drawing.edrw --user-data-profile edrawings_be_envelope_v1
edrawings-kit verify part.eprt --limits service
edrawings-kit extract part.eprt --entry entry:0 --output model.hsf
```

結果はUTF-8 JSONです。抽出先は明示指定し、既存ファイルは上書きしません。
コマンド、オプション、終了コードは[CLI仕様](docs/ja/cli.md)を参照してください。

## ドキュメント

- [Python APIガイド](docs/ja/api.md)
- [対応環境・形式・制限](docs/ja/support.md)
- [開発とテスト](docs/ja/development.md)
- [配布物のビルドと検査](docs/ja/distribution.md)

## ライセンス

[Apache-2.0](LICENSE)。依存ライブラリのライセンス本文と帰属情報を同梱します。
詳細は[NOTICE](NOTICE)を参照してください。
