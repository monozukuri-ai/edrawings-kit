# CLI仕様

インストール後の`edrawings-kit`と`python -m edrawings_kit`は同じ入口。
正常な結果はUTF-8 JSONをstdoutへ出す。入力を変更せず、ネットワーク参照も行わない。

| command | 結果 |
| --- | --- |
| `info` | Rust/backend version、契約版、実source hash、capabilities |
| `probe PATH` | 内容による形式判別 |
| `inspect PATH` | コンテナ・entry一覧。CRC検証やHSF解析は別操作 |
| `extract PATH --entry ID --output DEST` | 明示entryをDESTへ抽出。既存fileは上書きしない |
| `verify PATH` | 全entryのCRC/SHA-256検査 |
| `hsf-header PATH [--entry ID]` | HSFヘッダー |
| `hsf PATH [--entry ID]` | 有界HSF構文解析 |
| `scene PATH [--entry ID]` | 汎用sceneの保存要素 |
| `drawing PATH [--entry ID]` | 文書・図面inventoryと意味の対応状況 |

entry IDは`inspect`の`raw:0`／`entry:N`を使う。曖昧な複数eModelを勝手に選ばない。
PATHを持つcommandは`--limits desktop|service`を受け、既定はdesktop。
`hsf/scene/drawing`は`--mode partial|strict`、
`--user-data-profile disabled|edrawings_first_be_v2|edrawings_be_envelope_v1`と
`--image-profile disabled|edrawings_1910_u32_v1`を受ける。
profileは既定disabled、modeは既定partial。
`scene/drawing`の`--import-root`は明示された絶対segment文脈のinventory用である。

| 終了コード | stdout / stderr |
| --- | --- |
| 0 | 結果JSONをstdout。partial/unsupportedも含むので段階statusを確認する |
| 2: parser/I/Oエラー | stdoutなし、`{"error": {"code": ..., ...}}`をstderr |
| 2: 引数エラー | argparseのusageと説明をstderr。JSONではない |
| 0: `--help` | usageをstdout。JSONではない |

strictの未対応・破損・資源超過を成功扱いにしない。エラー文言ではなく`error.code`で判定する。
JSONはリダイレクト先やWindowsのlegacy code pageに関係なくUTF-8で出力する。
pre-alphaのため将来のschema互換性は未保証。`info`と使用版を結果と共に記録する。
