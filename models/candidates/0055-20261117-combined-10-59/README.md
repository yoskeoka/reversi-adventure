# 0055 部分学習候補の保存

この directory は project-owned table32 の phase 10–59 を含む結合候補の保存コピーである。
phase 0–9 は含まない。結合後の候補は未対局・未評価であり、採用モデルではない。
既定の TrainedEvaluator、Playground、0018 受け入れ状態を変更しない。

`candidate-artifact.json`、`manifest.json`、`prepare.receipt.json` は結合 root
`0055-20261117-combined-10-59` の原本を byte 単位で保存したものである。
`manifest.json` には作成時の絶対パスが含まれる。このコピーだけでは元の入力 root、
対局履歴、exposure keys を再現できず、元 root とその入力一式の代わりにはならない。
結合処理は入力の保存済み offline receipt を信頼し、入力となる manifest、artifact、
report、receipt、exposure の整合性と phase 重複を確認した。過去の探索・学習を再実行した
ことや、この候補の対局評価を完了したことを意味しない。

| 項目 | 値 |
| --- | --- |
| candidate file SHA-256 | `cffe40b3bc685cc5b3ae588aa1551dbbf4e719687ee5a970f7b2db28a5b3e278` |
| internal artifact digest | `a0b638155b50daca1a2ebb841d1ed2c11caec6de6347cdc0ec1531f8dcd40cac` |
| weight digest | `17fc1cba3abe270fdde81b482f91c47e3211b8388bc149bf2033180e93aaebfa` |
| manifest SHA-256 | `e9893ba1ddb2123657daad3fa9fda732297af1cc7fdb665a39751e82d0bf26d9` |
| prepare receipt SHA-256 | `b07e0a648420098d98903efce89b61702c4a45e314307ed86b6969ddd70dfdbd` |
| identity | `reversi-ai-pattern-table32-partial-v1` |
| producer commit | `2f68a89b13cb86af758619b2bf2d9c1a6a4d52e0` |
| input exposure digest | `057e404207b0f3ec0f3da9e1236b896d8d06c06a70cf5091c0ee6d5709513ed0` |

元の run roots は workspace の `.local/reversi-ai-runs/` 以下に保持される。
以下の digest は各 source artifact の internal digest である。

| phase | root | artifact digest |
| --- | --- | --- |
| 10–19 | `0054-20261114-phase10-19` | `5679ca5e47000add6c020fa2018bf7e69a5bcf41ffebef05e91a4d7292d3e544` |
| 20–29 | `0054-20261114-phase20-29` | `b400bb04ee8d12b14270e41142719a56c6861e1edfeb56ea4c33bcfd18d49014` |
| 30–39 | `0054-20261114-phase30-39` | `2c7719ecfd5b72179ce8c66e919852c03ba40faa3e35a78acb289a2848bd2323` |
| 40–49 | `0054-20261111-partial-01` | `4e3430d6de453218e2d447ca1844fb7ec747a99fe10881b6458b7fa5abacd72c` |
| 50–59 | `0054-20261114-phase50-59` | `ec278217c0c3f17dfd5a43e173406bcca9151bd2c9c15a85209aff3fe03724a5` |

phase 40–49 の元候補は単独対局で `not-improved-at-pilot-scale` だった。
それは結合候補の評価結果ではない。すべての phase が揃った場合でも、従来の full pilot と
同一条件・同一強度であることや、0018 の受け入れを意味しない。
