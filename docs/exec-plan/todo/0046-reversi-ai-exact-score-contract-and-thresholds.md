# 終局score差を調査し、必要な探索深度を明示設定できるようにする

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

全体目標は計算資源ハンデ付きOracleへの勝率50%である。現在は強化学習を回せる速度へ
探索エンジンを改善する前段であり、性能改善とscoreバグ調査を先に進める。
強化成功/50%勝率をエンジン改善の開始条件にしない。

空き16系列のCLI ±39 / Oracle ±40という差を、保存済み証拠と短い終局fixtureで調査する。
同時にGodotと自己対局実行で必要な探索深度・exact閾値を明示設定できるようにする。
ユーザーの2026-10-08の指定は「必要な読みの深さが選べること」であり、既定値を20にする変更ではない。
16/20だけの選択肢へ固定せず、18/22/24なども設定できるようにする。
既に柔軟なPlayground/CLIの範囲と、既定値・既存presetは維持する。

完了は、原因を確認した証拠または上限内で確認できなかった範囲の記録、
設定伝達・manifest互換・資源制限応答の検証、0040への引き継ぎ、PR handoffまで。
score差の解消、本番game再利用、24の時間内完了、強化成功、0018勝率達成を自動的に主張しない。
score規則の変更が必要と判明した場合は、影響と代案を人間へ示し、別の修正計画を作る。
調査結果が未確定の場合もその証拠を残し、0040の正確性阻害条件を解除しない。

## 参照

- [PR #255](https://github.com/yoskeoka/reversi-adventure/pull/255) — 0045の固定6局、6 root/10 query、report sealと制約。現在OPEN、実装開始前にmerge状態を確認する。
- `docs/references/reversi-ai-exact-threshold-reuse-assessment.md:142-149,196-203` — 保存score差と24のpilot時間切れ。
- `docs/specs/reversi-ai.md:988-1011`、`rust/reversi-ai/src/search/endgame.rs:959` — projectの終局score、wipeout ±64、exact結果。
- `tools/reversi-ai-oracle/oracle.py:1156` `effective_query` — pass時の手番と符号。
- `tools/reversi-ai-benchmark/whole_game.py:742`、`exact_threshold.py:563` — 終局child照合のscore式。
- `rust/reversi-ai/src/config.rs:11-32,69-94` — 既定exact16、固定`strong_engine_hcap_v1`、decision設定の範囲。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:22-40,59-66,147-160` — 通常CLIの設定受理とAdvisor/decision設定。
- `rust/reversi-godot/src/bridge.rs:166-189` `set_ai` — 3phase深度は指定できるがexact引数がない。
- `tools/reversi-ai-training/reinforcement.py:163-205,478-485,645-671,710-721` — schema4検証、自己対局設定、candidateとの引数結合。
- `tools/reversi-ai-playground/server/session.mjs:9,55-69` — 既存exact0..30。24は既に選択可能。
- `tools/reversi-ai-oracle/oracle.py:168-178,210-233` — 固定strong-v1と実験profile。
- [現在の判断材料](../../references/reversi-ai-current-status.md)、`0040-reversi-ai-self-play-performance-closeout.md`。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — score調査の結果分類、明示設定、schema別互換、資源制限時の契約をコード前に定義。
- (NEW) `docs/references/reversi-ai-exact-score-contract.md` — 証拠identity、両score式、終局盤面、原因/未確認範囲、修正候補。
- (NEW) `tools/reversi-ai-benchmark/fixtures/exact-score-contract-v1.json` — 元receiptのdigest、盤面/手番/選択手、保存Oracle値、合法continuationと終局fixture。
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs` のtests — production score式を変えず、独立referenceによるterminal/root/childの調査用回帰を追加。
- (MODIFY) `tools/reversi-ai-benchmark/` と関連tests — project/Oracle score契約、pass、終局childの監査。原因を確定できる範囲の小さい照合修正だけを行い、旧receiptは維持。
- (MODIFY) `rust/reversi-godot/src/bridge.rs`、tests — 旧`set_ai`互換を保つ明示exact設定API。
- (MODIFY) `tools/reversi-ai-training/reinforcement.py`、関連tests、README、`Makefile` — 自己対局専用3phase/exact設定、新schemaと伝達。
- (MODIFY) `docs/references/reversi-ai-current-status.md`、0040/0019/0037 — 実装結果・設定選択と本番freezeの境界を同期。
- (NEW, 必要な場合だけ) 原因に絞ったscore規則/solver修正計画。採用はこの調査結果から別途判断する。
- (DELETE, 完了時) 本計画。別計画や0040の未達を本計画と共に削除しない。

## A. score差の調査

1. 元の固定directoryはworkspace `.local/reversi-ai-whole-game-0035/exact-threshold-0041-42f6d57/`。
   `pilot-oracle/pilot-16-8-turn-window-2-seat0-position-11.json` のseal
   `71e3d66ee22711778bdfd3155b0f52989d56c4ef488712936eecf2460f77675b`を再計算し、実ファイルSHA-256もfixtureへ固定する。
   空き13・白手番の盤面は `..BBBBWW..BBBWWW..BBWWWW.BBBWWWW.BBBBWWW.BBBBBWW..BWWWWW..WWWWWB`。
   CLIはb7/+39、保存Oracleはb7/+40と選択child黒視点-40。全局再測定ではなくこのrootから始める。
   元の失敗receiptを成功へ変更せず、元producerと現行sourceを区別する。
2. projectは両色生存の終局で実石数差、wipeoutだけ±64。
   固定Egaroucid v7.8.1は勝者へ残り空きを加算する。
   workspaceの固定Oracle source `oracle-cache/source/src/engine/board.hpp:378` と
   `evaluate_common_7_4.hpp:227`をsource archive digestと共に確認する。
   これだけで観測差の原因を確定せず、合法PV/terminal leafを保存して実石数・空き数・両式を独立再計算する。
3. 新しい短い探索は上記rootとb7 childのみ、project式/Oracle式それぞれの独立referenceを最大4 solve。
   1 solveは30秒、RSS 1,572,864 KiBを上限にし、未完了は保存して追加root・自動retry・上限延長をしない。
   通常回帰は小さい終局fixtureだけを使い、空き13の調査をCI毎回の必須solveにしない。
   新規Oracle solveと16/20/24全局計測は行わず、保存済みcomplete queryを利用する。
4. 満盤、空きあり両色生存の早期終局、draw、wipeout、空盤、forced pass、terminal childを検査する。
   root値だけでなく選択childの値と合法continuationを各score契約で確認する。
   rootへ一律±1を足して一致させない。終局leafの値が異なるとminimaxの手順/順位も変わり得る。
5. 原因分類を「score契約差をterminal/root/childまで確認」「符号/手番/validatorの誤りを確認」
   「solver誤りの証拠あり」「上限内で未確定」に分け、証拠と未確認範囲を記録する。
   project規則維持とOracle規則への変更の影響（training labels、golden/corpus、cache identity、manifest）を示す。
   score意味の変更をこの計画で暗黙に選ばない。未達の独立一致は0040に残す。

## B. 必要な深度・exact閾値の明示設定

1. 通常CLIは既に任意の正のu8深度とu32 exact引数を受理する。既定と範囲を変更しない。
   Advisor/decision/Playgroundのopening1..12、midgame1..16、exact0..30も維持する。
   exact0は無効化、20/24は空き数の切替閾値でありheuristic depthと区別する。
2. Godotに`set_ai_with_exact_threshold(evaluator, opening, midgame, endgame, exact)`を追加する。
   旧`set_ai(evaluator, opening, midgame, endgame)`は互換維持。
   新APIは3phase深度1..64、exact0..30を整数のまま検証してから変換する。16/18/20/22/24がそのまま届く。
   不正値はfalseで拒否し、AI設定を一部だけ変更しない。可視UIと対局進行はGodot側が所有する。
3. reinforcementの新schema5では`self_play_search`だけを柔軟にする。
   自己対局専用opening/midgame/endgame/exact引数を独立させ、深度は各1..64、exactは0..30を受理する。
   既存`--self-play-midgame-depth`に加え、`--self-play-opening-depth`、`--self-play-endgame-depth`、
   `--self-play-exact-solver-empty-squares`を用意する。
   Make変数から同じ値を渡し、manifest/reportが全値・CLI SHA-256・資源上限・turn policyを固定する。
   既定12/12/12・exact16は変えない。既存の明示midgame8も維持する。
   candidate-match/regret/0018の`strong-engine-hcap-v1`は12/12/12・exact16を維持し、自己対局引数で変化させない。
4. 新規prepareはschema5を生成し、runが記録値を実行する。旧schema3/4の完成reportは元契約でoffline検証する。
   新prepare/runの入口はschema5へ移行し、旧manifestを新設定や新policyへ暗黙に読み替えない。
   中断した旧runのresume可否をREADMEへ明示し、別identityでの再開を拒否する。
5. 24が指定可能であることと制限内の完了は別。budgetによる未完了をexact=true/完成scoreにしない。
   学習のtimeout/未完了は既存fail-closedを維持し、教師値へ使わない。
   本計画はgame再利用の本番有効化、default20、学習batchや0018 profileの変更を含めない。
   Aで未解決の正確性条件が残る間は、本番freezeのgateを通さない。

## 依存関係・順序

- 現行main `1f2eb5a`から計画した。PR #255はOPENなので、本計画実装前にmerge/rebaseと最新の0040記録を確認する。
- spec更新→Aのfixture/調査記録→Bの設定/manifest実装→検証→0040へ引き継ぎ。
  AとBのread-only調査は並行可。Git writesとspec/code更新は直列に行う。
- 0032は[PR #223](https://github.com/yoskeoka/reversi-adventure/pull/223)で完了・削除済み。
  本番入力再検証は0019のfreeze責任であり、0032を復活させない。
  現行sourceとの差と凍結producerでの検証失敗を区別する。
- 0040は設定/時間予算/採否の人間判断を持つ。0037 pilot→0019の完成候補→0018の勝率受け入れを飛ばさない。
- 性能改善は既存0035/0040と0029/0030/0036の対象・証拠を確認して進める。
  0045の平均wall/exact/heuristic差からcacheだけを最適化対象と決めない。
  本計画の柔軟な設定は改善を評価する基盤であり、それだけで学習速度改善完了と扱わない。
- 長い自己対局/Oracle測定をagentは起動・待機・監視しない。追加測定が必要なら件数と上限を別計画で定義する。

## 検証

- 保存receiptのseal/実ファイルdigest、合法replay、終局score式、pass符号、root/childの独立再計算。
- 既定不変、明示18/22/24の設定伝達、範囲外/負数/変換overflowの拒否、旧Godot API互換。
- schema3/4のoffline意味維持、schema5のselfplay全設定、candidate-v1固定、改変digestの拒否。
- 19/20/21・23/24/25空きの切替を低いbudgetのfixtureで検査し、24の長い完全solveをtest条件にしない。
- turn policy、局開始reset ack、未完了score/教師値のfail-closed、保存失敗の不変性。
- 該当Rust/Python tests、Clippy、Godot build、fmt、workflow lint、diff check。
- 根拠・残条件の記録後に本計画だけを削除し、`review-task`で最新headを確認する。

## Addresses

- N/A
