# Python APIガイド

`edrawings_kit`はRustで入力を解析し、不変のPython dataclassとbytesバッファを返します。
summaryやメタデータのモデルは`to_dict()`でJSON互換の辞書に変換できます。
公開型には型注釈を同梱しています。

## 入力とentry

```python
import edrawings_kit as ed

info = ed.inspect_file("part.eprt")
doc = ed.read_file("part.eprt", limits=ed.Limits.desktop())
for entry in info.entries:
    print(entry.id, entry.name, entry.bytes)

checks = doc.verify_all()
payload = doc.extract(info.hsf_candidates[0])
print(payload.info.sha256, len(payload.data))
```

ファイル入口は`probe_file` / `inspect_file` / `read_file`、bytes入口は
`probe` / `inspect` / `read`です。名前の拡張子ではなく内容から形式を識別します。
`read_file`は入力のスナップショットを保持するため、後から元ファイルが変更されても影響しません。

`inspect`はentryを展開せず、CRCは未検査です。`verify_all()`は全entryを検証します。
`read_file(..., verify_all=True)`でも全entryの検証を要求できます。
ZIPのentry名は自動展開先に使いません。同名entryは`entry:N`というIDで区別します。
複数のHSF候補がある場合は、利用者がentryを指定してください。

```python
header = doc.inspect_hsf("entry:0")
parsed = doc.parse_hsf("entry:0", mode="partial")
```

## 解析状態と例外

| 状態 | 意味 |
| --- | --- |
| `not_requested` | その段階は未実行 |
| `complete` | その段階・プロファイルの対象範囲を取得済み |
| `partial` | 確定した部分を取得したが、未対応または欠落がある |
| `unsupported` | 意味や処理に未対応 |

`complete`は全eDrawings形式への対応を意味しません。形状の定義、配置、描画設定、
文書の意味には別の状態があります。`scene.status`だけで表示の再現性を判断しないでください。

`EdrawingsError`以下に`InvalidFormatError`、`UnsupportedFeatureError`、
`LimitExceededError`があります。`error.diagnostic.code`は機械判定用の識別子です。
I/Oエラーは`OSError`系です。`partial`でも破損や制限超過を成功に変換しません。

```python
try:
    scene = doc.read_scene(mode="strict")
except ed.UnsupportedFeatureError as error:
    print(error.diagnostic.code)
```

## 実験プロファイル

`parse_hsf` / `read_scene` / `read_drawing`は次の引数を受け取ります。

| 引数 | 値 | 用途 |
| --- | --- | --- |
| `user_data_profile` | `disabled`（既定） | 製品固有User Dataを解釈しない |
| 同上 | `edrawings_first_be_v2` | 対応する先頭User Dataの境界・fieldを取得 |
| 同上 | `edrawings_be_envelope_v1` | 対応する先頭・末尾User Dataを取得 |
| `image_profile` | `disabled`（既定） | 実験的な画像規約を有効にしない |
| 同上 | `edrawings_1910_u32_v1` | 対応する画像定義の保存値と出典を取得 |

実験プロファイルの採用はdiagnosticsに残り、strictでは拒否します。
意味を確定できないUser Dataや描画設定が残る場合、インスタンス配置を抑止することがあります。
未知の版や長さを推測して読み飛ばしません。
`scene` / `drawing`の`import_root`は明示的な絶対segment文脈を指定するための引数です。
外部ファイルを取得したり、未知の親属性を補完したりするものではありません。

## メッシュと配置

```python
scene = doc.read_scene(user_data_profile="edrawings_be_envelope_v1")
print(scene.summary.status, scene.summary.placement_status)
for mesh in scene.summary.meshes:
    buffers = scene.mesh_buffers(mesh.id)
    print(buffers.vertices.dtype, buffers.vertices.shape)    # <f4, (N, 3)
    print(buffers.triangles.dtype, buffers.triangles.shape)  # <u4, (T, 3)
    vertex_bytes = buffers.vertices.data
```

バッファは不変bytesへのコピーで、NumPyは必須ではありません。必要なら
`np.frombuffer(buffer.data, dtype=buffer.dtype).reshape(buffer.shape)`で利用できます。
頂点は局所座標です。配置が確定したインスタンスは`scene.summary.instances`に別途返します。
行列はrow-major / row-vectorで、合成順序は`p_world = p_local * local * parent`です。

未知の単位・色・可視性は`None`として保持します。単位変換や法線の自動生成は行いません。
三角形への変換に未対応の面は元のface情報を保持し、三角形バッファを保留する場合があります。
`triangle_faces`で生成三角形と元の面の対応を取得できます。

## 図面・文字・文書構造

```python
drawing = doc.read_drawing(user_data_profile="edrawings_be_envelope_v1")
for primitive in drawing.summary.scene.primitives:
    points = drawing.primitive_points(primitive.id)
    if primitive.text is not None:
        print(primitive.text.value, primitive.text.encoding, primitive.text.status)
        raw_text = drawing.source_bytes(primitive.text.source)

print(drawing.summary.sheet_inventory)
print(drawing.summary.component_inventory)
print(drawing.summary.configuration_inventory)
print(drawing.summary.drawing_plane_profile)
```

sheet/view・部品・構成は対応する保存規約から取得します。部品行列は局所値です。
active構成や一般的な有効表示状態は補完しません。図面XYの単位は検証条件に合うwriterに限定し、
元CAD原点やモデル寸法への逆変換を保証しません。
文字は既知のASCII・ISO-8859-1・UTF-8・Unicode16/32規約を厳密に復号します。
未知encodingでは原情報を保持し、不正な既知encodingはエラーにします。
寸法の表示文字から真値・公差・幾何参照を生成しません。

`read_drawing(mode="strict")`は文書意味まで要求するため、現在は未対応の例外になります。
汎用要素の厳密検査には、対応する入力で`read_scene(mode="strict")`を使ってください。

## 出典と資源制限

`source_bytes(span)`は指定された展開後domain内の元バイトを返します。
コンテナのoffsetと内部圧縮後のoffsetは異なる座標系です。両者を加算して使用しないでください。

`Limits.desktop()` / `Limits.service()`で入力、展開量、出力、record、node等の上限を設定します。
個別の上限も`Limits(max_file_bytes=..., max_output_bytes=...)`で指定できます。
これらはパーサの消費予算であり、プロセス全体のRSS上限ではありません。
JSON化や利用側の配列コピーにも別途メモリが必要です。
