# AI終局scoreをEdax/Egaroucidの勝者空き加算へ統一する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

2026-10-08のユーザー指定「Edaxも同じルールなら合わせたい」に従い、AI探索と新規学習入力の
終局scoreへ `winner-empty-v1` を採用する。固定Edaxの `solve` は勝者へ残り空きを加算し、
0046で確認した固定Egaroucid v7.8.1の規則と一致する。この規則を明示採用する。
0046の調査・設定伝達とは別のscore意味変更として実装する。

完了は、spec、共通終局式、score/cache/artifact/data/manifestのidentity、旧証拠のoffline互換、
Oracle/benchmark validatorの移行、小さいfixtureでの独立一致、PR handoffまで。
本番入力の再生成・再学習、0037 pilot、0019 cycle、0018勝率受け入れは本計画の完了条件にしない。
それらが済むまでproduction freezeを解除しない。エンジン移行完了と本番採用を区別する。

## 依存と参照

- [0046実装PR #257](https://github.com/yoskeoka/reversi-adventure/pull/257)
  （計画時head `8d59d97`）をmergeしてから最新mainで実行する。
  0046のschema5、設定範囲、調査fixture/reportを前提とし、本計画で0046を再実行しない。
- [Edax固定source](https://github.com/abulmo/edax-reversi/blob/14f048c05ddfa385b6bf954a9c2905bbe677e9d3/src/endgame.c#L30-L39)
  — commit `14f048c05ddfa385b6bf954a9c2905bbe677e9d3` の `solve`、勝者空き加算。
- `docs/references/reversi-ai-exact-score-contract.md`、
  `tools/reversi-ai-benchmark/fixtures/exact-score-contract-v1.json` — 0046の両score式、保存receiptのseal/digest、
  root/選択child、合法PV/terminal leaf。空き13の独立reference最大4 solveを再利用する。
- `rust/reversi-ai/src/search/endgame.rs:959-969` `terminal_score`、
  `search/negascout.rs:200-207` — exact/heuristic両方のterminal処理。
- `rust/reversi-ai/src/search/mod.rs:135-163` `SEARCH_SEMANTICS_VERSION`、
  `search_context_fingerprint`、`advisor_identity` — contextとAdvisor identity。
- `rust/reversi-ai/src/eval/pattern.rs:9-13,64-69,135-150`、
  `eval/trained.rs:18-22,59-66,135-157,198-210` — format1、score scale、provenance、runtime loader。
- `tools/reversi-ai-training/training.py:20-29,156-168,194-203,292-345` — trainer/target/feature契約、artifact digest。
- `tools/reversi-ai-training/random_inputs.py:18-21,130-186,193-230,264-273` — v1 generator/source、source digest、raw差labels。
- `tools/reversi-ai-training/reinforcement.py` `validate_manifest`、`play`、`replay`、`cycle`、`verify`、
  `prepare`、`regret_command` — 0046後のschema3/4/5、raw差教師値とcandidate固定設定。
- `tools/reversi-ai-oracle/oracle.py:1438-1447` — terminal childのraw差shortcut。
  `golden_projection`、`verify`/`generate-golden` — golden identityと照合入口。
- `tools/reversi-ai-benchmark/whole_game.py:374-377,735-785` — 実石数のgame記録とOracle terminal child。
  `exact_threshold.py:24,563`、`exact_cache_verification_oracle.py:10-39` — v1 identityと旧terminal式。
- `docs/exec-plan/todo/0040-reversi-ai-self-play-performance-closeout.md`、
  `0037-reversi-ai-training-method-pilot.md`、`0019-reversi-ai-pattern-reinforcement-cycle.md`、
  `0018-reversi-ai-strong-engine-acceptance.md`、`docs/references/reversi-ai-current-status.md`。

## 採用するblack-box契約

### AI scoreと盤面上の得点

手番側の実石数 `own`、相手実石数 `opponent`、`empty = 64-own-opponent`、
`d = own-opponent` とし、両者合法手なしの終局で `d + sign(d)*empty` を返す。
drawと空盤は0、片色のみの盤面は±64、満盤は従来と同じ実石数差。
符号はqueryの手番視点、選択childの反転とforced passは現行の合法手番処理を維持する。
AI root/PV/childの全leafへ同じ式を適用する。一律±1のroot補正や、旧root値の再ラベルはしない。
minimaxの順位/PVが変わる可能性をspecと引継ぎに明記する。

`Board::count`、engine `Game::score`、勝敗、Godot `get_score`、盤面UIの実石数表示は変更しない。
実石数を記録する `disc_counts`、random gameの `black`/`white`、whole-gameの物理 `score_black` は維持し、
新AI/教師scoreと混同しない。数値範囲±64、feature数64、phase数60、catalog、weight bounds、
normalization divisor64、3phase/decision設定範囲、既定exact16、全preset、turn policyを維持する。

### 新identityと拒否境界

| 対象 | 新規契約 | 旧証拠の扱い |
| --- | --- | --- |
| AI探索 | `score_contract="winner-empty-v1"`、`SEARCH_SEMANTICS_VERSION=2`、Advisor prefix `project-ai-advisor-v2` | 旧cache/context/Advisor identityを共有しない |
| trainer/record | `reversi-ai-pattern-training-v2`、trainer manifest/record schema2、`target.semantics="winner_empty_v1_for_side"` | schema1/raw差は明示legacy offlineのみ |
| artifact/feature | format2、feature `format_version=2`、`score_scale="winner_empty_v1"`、明示 `score_contract="winner-empty-v1"` | format1は新runtime/prepareへ渡せない |
| reinforcement | producer `reversi-ai-pattern-reinforcement-v4`、manifest schema6、game/report/checkpoint schema4、明示score contract | manifest3/4/5とreport/checkpoint3を元producer/shapeでoffline検証 |
| random input | `reversi-ai-random-inputs-v2`、`project-owned-random-games-v2`、manifest/output/game/record schema2、明示score contract | v1 source/manifest/dataは凍結producerでoffline検証 |
| Oracle正規化 | golden/analysis schema2と明示score contract | schema1 golden/receiptを上書きせずlegacy projectionでoffline検証 |
| whole-game | `reversi-ai-whole-game-v3`、manifest schema2、report schema3、evidence schema2と明示score contract | 既存単局schema1とresumable schema2のreport、seal、source/binary identityを保持 |
| threshold/cache assessment | `exact-threshold-assessment-v2`、`exact-cache-verification-v2`、新receipt/queryのscore contract | v1 receipt/queryは元契約のoffline adapterへ分岐 |

`TRAINED_EVALUATOR_VERSION=2` とし、runtime fingerprintへscore contractを含める。
pattern formatを変えてもfeature抽出/catalogを変えない。trainer provenanceの許容producerとoptimizerの対応も
version別に検証し、新artifactへ旧trainer名を付けることを拒否する。

旧artifact/record/reportを新設定へ暗黙に読み替えない。Pythonのlegacy検証は明示
`--legacy-offline` でのみ利用し、CLI/Godotの新runtimeは旧artifactを拒否する。
reinforcement `run`/`regret-command`/`regret-timeout` はschema6だけを受理する。
schema3はpolicyなし、schema4/5はturn policyありという元shapeを保持し、schema5の柔軟な設定も保持する。
旧reportの教師値は当時のraw実石数差としてreplayし、solverの旧wipeout例外へ勝手に変更しない。
schemaの数字、producer文字列、score contract、artifact scale、CLI SHA、source digestが不整合なら拒否する。
digestを再sealした意味変更も独立検証で拒否する。

v1 random manifestは現行source digestと一致しないため、旧source snapshot/commitを保存した隔離offline
検証を利用する。新sourceへ旧digestを置換しない。移行ツールが必要なら、原本と凍結producerを入力にして
別directoryへschema2の新identityを生成し、対応関係と原本digestを記録する。新labelは合法replayで確認した
terminal boardから計算する。root/goldenのminimax値はterminal情報だけから移植しない。
その本番データ移行・再学習batchは別の人間操作計画で件数/上限/進捗/再開契約を固定する。

### validator修正とgate

Oracle terminal-child shortcut、whole-game terminal-child、threshold/cache検証の旧score式は
本計画に直接関係する既知の不整合として修正する。新契約では同じ独立winner-empty式で照合し、
旧receiptはversion別adapterで元の式を再現する。保存された不一致/未完了を成功へ書き換えない。
Oracle corpusのschema1は盤面/合法手/実勝敗の契約なので維持し、scoreを持つgolden/referenceのみ別identityにする。
既存 `golden.jsonl`、`reference-v1.jsonl`、学習原本とreceiptは維持する。新しい小さい
`winner-empty-v1` fixture/goldenを別ファイルへ保存し、新codeの回帰に使う。
新規本番golden/referenceの全量Oracle生成はこの実装では起動しない。

本番freezeは移行だけでは解除しない。0040の最新producerでの独立root/選択child一致、資源制限応答、
人間の設定/性能判断、0037 pilot、0019の新契約baseline/validation入力と候補cycle、0018の
ハンデ付きOracle受け入れをそれぞれ残す。strong-engine-hcap-v1の12/12/12・exact16を変更しない。
game cache本番化、default20、長い24 solve、強化成功/50%勝率は含めない。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 上記score、identity、拒否、legacy offline、物理score分離、gateをコード前に規定。
- (MODIFY) `rust/reversi-ai/src/search/endgame.rs`、`search/mod.rs`、`search/negascout.rs`、`explain.rs`、関連tests — 共通terminal式、identity、score説明、独立回帰。
- (MODIFY) `rust/reversi-ai/src/eval/pattern.rs`、`eval/trained.rs`、関連tests — format/scale/provenance/runtime rejection。
- (MODIFY) `rust/reversi-ai/src/bin/reversi-ai-cli.rs` と必要なPlayground protocol/tests — score contract出力/解析と新Advisor identity。
- (MODIFY) `tools/reversi-ai-training/{training.py,random_inputs.py,reinforcement.py}`、tests、README、Makefile — 新schema/labels/legacy入口。
- (NEW) 小さいschema2 training/random/reinforcement fixturesとwinner-empty golden、migration互換fixture。
- (MODIFY) `tools/reversi-ai-oracle/oracle.py` とtests、benchmarkのwhole-game/threshold/cache/reference validator — terminal shortcut、version分岐、identity検査。
- (NEW) `docs/references/reversi-ai-winner-empty-migration.md` — old/new契約、保存identity、tiny検証と人間batchの残条件。
- (MODIFY) current-status、0040/0037/0019/0018 — freeze入力と最新契約の引継ぎ。
- (DELETE, 完了時) 本計画のみ。既存gate計画と未達の人間作業は削除しない。

## 実行順序と検証

1. 0046のmerge/latest main、保存fixture/digestとEdax/Egaroucid固定sourceを確認する。
   specへ採用契約を反映する。read-only調査は並行可、spec/codeとGit writesは直列。
2. 共通terminal式とidentityを変更し、満盤、両色生存の空きあり終局、draw、wipeout、空盤、
   forced pass、terminal childを小さい独立referenceで確認する。root/selected child/PV leafを別々に検証する。
   cacheのLower/Upper/exact bound、collision、interruption、context切替、reset回帰も新意味で確認する。
3. 新artifact/trainer/data/manifest契約とtiny fixturesを実装する。schema3/4/5 complete reportのoffline
   元意味、schema6だけの実行、旧artifact runtime拒否、producer/digest/policy/score contract改変拒否を検証する。
   schema6自己対局の全設定伝達とcandidate固定、timeout/未完了教師値のfail-closedを確認する。
4. Oracle/benchmark shortcutとversion別adapterを実装する。小さいfixture/stubでpass符号、terminal child、
   新root/child一致、旧失敗receipt不変を確認する。旧golden/referenceを新scoreへ自動変換しない。
5. Rust engine/AI tests、training/Oracle/benchmark Python tests、必要なPlayground tests、
   Godot build、Clippy、fmt、workflow lint、diff checkを実行する。
   0046空き13の調査solveをCI必須条件にせず、agentは新規Oracle solve/whole-game/長い学習batchを
   起動・待機・監視しない。小さいfixtureでの検証をエンジン移行の証拠とする。
6. migration referenceと残gateを同期し、PR準備後に本計画を削除する。
   `post-task-review` と `review-task` の最新head follow-upでhandoffする。

## Addresses

- N/A
