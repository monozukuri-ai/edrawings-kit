# 対応環境・形式・制限

[English](../support.md) | 日本語

## 実行環境

| 項目 | 対象 |
| --- | --- |
| Python | CPython 3.10–3.14、通常のGIL付きbuild |
| Linux wheel | x86_64、glibc 2.34以上 |
| Windows wheel | x86_64 |
| macOS wheel | arm64、macOS 11以上 |
| ソースbuild | Rust 1.88以上、maturin/PyO3 |

wheelは`cp310-abi3`形式です。CIではLinuxのPython 3.10–3.14、Windows/macOSの3.10と3.14を試験します。
Windows/macOSの3.11–3.13、free-threaded Python、PyPy、その他architectureは未認定です。
パーサの動作にはeDrawingsやHOOPS SDKを要求しません。

## ファイルとデータ

| 対象 | 対応範囲 |
| --- | --- |
| コンテナ | raw HSF、通常ZIP、対応する92-byte前置き付きZIP |
| ZIP | Store/Deflate、entry一覧、上限付き抽出、CRC/SHA-256 |
| HSF | 8.05 / 14.50 / 19.10の限定命令群、内部zlib、出典と未解析範囲 |
| 形状 | 対応するShell/Mesh、線・ポリライン・ポリゴン・円／円弧の保存値 |
| 文字 | 既知encodingの復号、raw bytesと出典の保持 |
| 属性 | 対応する色・可視性・行列・線種・font・glyph・描画設定の保存情報 |
| 文書 | 対応するsheet/view、部品ツリー・局所変換、複数構成、限定図面単位 |
| 製品固有User Data・画像 | 明示指定する実験プロファイルのみ |
| 表示用の束 | 保存されたsegment木・行列・include・repeat instanceからの推定配置、1構成、HSF／`materials.xml`／`defaultcolor`の色、オプション・text・User Index Dataからの名前、記録があれば`model_units`、active構成とeDrawingsの表示状態による可視性（隠れた部品は既定で除外）、プレビュー画像の抽出 |
| 書き手 | SOLIDWORKSのeDrawings書き手（HSF 19.10、2014〜2026）と、eDrawings 2026のHOOPS Exchange取り込み（19.10ヘッダの下に3DF 20.10のレコード: priority、user index data、3語のrendering options、バッククォート付きの名前）、古い8.05／14.50プロファイル |

ZIP64、分割・暗号化ZIP、未知圧縮、対応プロファイル外のHSFやwriterは対象外です。
メッシュ圧縮、LOD、画像／Texture、Style参照、クリップ等にも未対応の意味処理が残ります。
詳細な利用可能機能は`edrawings_kit.build_info()`または`edrawings-kit info`で確認できます。

## 結果の解釈

形状定義を取得できても、world配置や最終表示が確定しているとは限りません。
`placement_status`、文書の`assessment`、各inventoryと属性のstatus、diagnosticsを確認してください。
既定では未解釈の情報がある場合に確実でない配置を生成しません。`read_display()`と
`placement="scene_graph_v1"`は推定値を返し、推定であることを診断で明示します。

全eDrawingsファイルへの対応、公式Viewerと同じ表示、編集可能なB-Rep／履歴、
元CADの寸法・公差・原点の復元、CAD形式への書き出しは提供していません。
ファイルの拡張子や保存された数値文字だけを根拠に、単位や寸法の意味を補完しません。

APIおよびJSONは0.x版の更新時に変更されることがあります。利用版と`build_info()`のbackend identityを記録し、
更新時に使用する入力・出力の互換性を確認してください。
