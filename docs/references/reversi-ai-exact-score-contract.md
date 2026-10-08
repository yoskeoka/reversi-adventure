# 終局score契約の独立調査（0046）

## 結果と範囲

分類は **score契約差をterminal/root/childまで確認**。保存CLIの白+39と保存Oracleの白+40は、
両色生存・空き1の終局を異なるscore式で評価した結果である。
符号・手番・選択childの伝達はこの盤面で正しい。今回の独立探索にsolver誤りの証拠はない。
他の盤面・0045の6局・本番凍結producerの正確性全体は検証していない。
0040/0019の独立一致gateと本番freezeは解除しない。

## 証拠identity

固定証拠はworkspace
`.local/reversi-ai-whole-game-0035/exact-threshold-0041-42f6d57/pilot-oracle/pilot-16-8-turn-window-2-seat0-position-11.json`。
元receiptは`failed`、理由`independent Oracle score/continuation mismatch`のまま保存した。
実ファイルSHA-256は`2326dd81f616dc025a192b013f689d7e19f71f4d58ba7d72b4db338c837a46f6`。
`report_digest`を除くJSONをkey順・compact形式・末尾改行で再計算したsealは
`71e3d66ee22711778bdfd3155b0f52989d56c4ef488712936eecf2460f77675b`で保存値と一致した。

元harness revisionは`42f6d575b7115b4ccd6aa2ab6d9d805adadc1b89`、
CLI SHA-256は`0a7535bdf48b640dcc48cda41b1739b927b76b6cfb13b8dab30af312096775d5`。
これらは今回の現行source/独立referenceとは別identityである。
元harness各ファイルのdigest、manifest/jobのdigest、保存query、独立探索のsealは
[fixture](../../tools/reversi-ai-benchmark/fixtures/exact-score-contract-v1.json)へ固定した。

OracleはEgaroucid v7.8.1、source archive
`https://github.com/Nyanyan/Egaroucid/archive/refs/tags/v7.8.1.tar.gz`。
workspace固定archiveの実SHA-256は
`173af642276216a284498f8d7e32de23dbb9dc6611686c370b0de3eddbc1238b`でpinと一致。
保存Oracle binary SHA-256は`b97a36a29eb4dad32a18b9edafb9eb6776cef3a96b9c198c01102c22c7c0a148`。
固定sourceの`src/engine/board.hpp:378`（score_player）と
`src/engine/evaluate_common_7_4.hpp:227`（end_evaluate）の式を読んだ。
各ファイルSHA-256は順に
`a9d43ada0fe6e5349edc51b9836cc1f675b786fa16fc8e99f1f86b618d8a2fb1`、
`61b8a01ba0238ba2f7dddb8f93eb733152b3bb05abae35515e8f63d520690e90`。
両ファイルは固定archive内の対応memberとbyte単位で一致することも確認した。

## 両score式と合法continuation

手番視点の石数をown/opponent、空きをempty、実石数差をdとする。
projectは両色生存でd、wipeoutは勝者+64/敗者-64、空盤は0。
Oracleは`d + sign(d) * empty`。drawは0で、wipeout時はprojectと一致する。
rootへ固定±1を足す変換ではない。異なるterminal leafへの探索順位も変わり得る。

rootは空き13、白手番：

```text
..BBBBWW
..BBBWWW
..BBWWWW
.BBBWWWW
.BBBBWWW
.BBBBBWW
..BWWWWW
..WWWWWB
```

保存root queryは白b7/+40、b7 child queryは黒b8/-40。
両queryはcomplete/exact、`effective_side`は依頼手番と同じでsign=+1。
黒child値を負にすると白視点+40。CLIは白b7/+39。

独立referenceはmasked bit shiftによる合法手・反転と、TTなしalpha-betaを使う。
production Rust solver、Oracle coordinate adapter、Oracle binaryは探索に使わない。
root/child×project/Oracle契約の**計4 solve**だけを実行した。
各solveは30秒、RSS 1,572,864 KiB以下。address-spaceも同じbyte上限で制限した。
reference source SHA-256は
`a00a7806c952cc5d0b7a1d630088e5fb926a381fe982a203ae964cdf0e5fcb44`。

| 入力・契約 | 値 | wall秒 | nodes | peak RSS KiB |
| --- | ---: | ---: | ---: | ---: |
| 白root・project | +39 | 23.740 | 78,519 | 15,476 |
| 黒b7 child・project | -39 | 4.956 | 23,907 | 15,432 |
| 白root・Oracle | +40 | 8.645 | 70,964 | 15,528 |
| 黒b7 child・Oracle | -40 | 6.105 | 21,578 | 15,428 |

全4 solveが完成し、同じ合法continuationを保存した。
rootのPVは`b7 b8 b1 b2 a1 a2 a3 b3 a4 a5 a6 pass a7`。
childのPVは最初のb7を除く列。passは白の合法手がなく黒の合法手がある局面である。
終局は次の盤面となり、両色とも合法手がない。

```text
WWWWWWWW
WWWBBWWW
WWBWWWWW
WBWWWWWW
WWWWWWWW
WWWWBWWW
WWWWWWWW
.BBBBBBB
```

黒12・白51・空き1。白project scoreは51-12=39、Oracle scoreは39+1=40。
root値だけでなく選択b7 childのminimax値とPV終局値が各契約で一致した。
新規Oracle solve、追加root、retry、全局計測は実施していない。

## 通常回帰とvalidator境界

Python/Rustの通常回帰は満盤、空きあり両色生存の早期終局、draw、wipeout、空盤、
forced pass、terminal childを使う。空き13の探索はCIで再実行しない。
保存結果のseal、root/b7 child identity、各score値、PVの合法replay・終局値をofflineで確認する。
Python独立bitboardの合法手・反転はOracle adapterの座標実装とも短い対局で照合した。

旧`whole_game.py` schema1 producerのterminal-child式は実石数差だけであり、
早期wipeout黒63/白0/空き1でproject/Oracleの+64に対し+63になる。
旧`exact_threshold.py` v1はprojectのwipeout±64を含む式でterminal childを処理する一方、
非terminal childはOracle query値を使用するため、両色生存の早期終局では契約が混在する。
これらは歴史的receiptのvalidator/source identityを維持し、今回の新auditorで区別した。
今回の観測root/childは非terminal queryなので、このterminal-child問題は±39/±40の原因ではない。

将来の照合修正は新producer/versionを設け、project/Oracleのterminal値を別々に記録し、
異なる契約の値を一致判定へ直接渡さない契約を別計画で定義する。
旧失敗receiptを成功へ書き換えない。今回の新auditorは旧schemaの意味を変更しない。

## 採否と0040への引き継ぎ

2026-10-08にユーザーは「Edaxも同じ計算をしているなら、そこは合わせておきたい」と指定した。
Edax の固定commit `14f048c05ddfa385b6bf954a9c2905bbe677e9d3` の
[`src/endgame.c:30-39`](https://github.com/abulmo/edax-reversi/blob/14f048c05ddfa385b6bf954a9c2905bbe677e9d3/src/endgame.c#L30-L39)
の `solve` は `d + sign(d) * empty` と等価で、drawは0であることを確認した。
したがって採用する方向はOracle/Edaxへのscore規則統一である。
0046のproduction式は維持し、別の修正計画でlabel・cache・manifest・validatorの移行を定義する。

project規則を維持する場合、既存golden/training labelの意味は維持できる。
Oracle比較の目的を勝敗・合法選択・同一score契約での独立一致に分ける新validator設計が必要になる。
Oracle規則へ変更する場合、空きあり早期終局の教師値、golden/corpus、score semantics、
exact-cache identity、training artifact/manifest identityの移行と再検証が必要になる。
minimax選択手が全盤面で同じになる保証はない。

今回production score規則は変更していない。規則変更を採用する場合は人間の判断後に別修正計画を作る。
0040にはこの局面の原因確認を渡すが、旧producer/validatorの契約混在を解消した独立一致と
6局/Oracleを含む未達の正確性条件を残す。探索設定が指定可能になったことや今回の4 solveは、
24閾値の時間内完了・学習速度改善・本番game cache採用・勝率受け入れの証拠ではない。
