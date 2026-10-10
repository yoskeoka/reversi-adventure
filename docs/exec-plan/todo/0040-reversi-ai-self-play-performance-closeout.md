# 正確性修正と縮小検証の結果から自己対局設定を選ぶ

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

> **0047 score移行後の境界**: 新規AI/教師値は `winner-empty-v1`、artifact format2、
> trainer/record schema2、reinforcement manifest6・report4を使用する。旧schema3/4/5完成証拠と
> raw差baseline/validationは明示legacy offline検証だけに保持し、新runへ読み替えない。
> 本番入力の再生成・再学習は件数/上限/進捗/再開を固定した別の人間操作計画で行う。
> [移行記録](../../references/reversi-ai-winner-empty-migration.md)を参照する。
> 0040の最新producerでの独立root/選択child一致・資源制限応答・人間の設定/性能判断、
> 0037 pilot、0019の新契約baseline/validationと候補cycle、0018 held-out受け入れは未達として残す。
> strong-engine-hcap-v1の12/12/12・exact16とturn policyは維持し、移行だけでproduction freezeを解除しない。
> TrainedEvaluator自己対局の事前性能測定には、明示設定8/8/8・exact16・turnを選択する。
> これは候補比較/0018の12/12/12を変更せず、学習batch総時間とも区別する。

## 目的と完了条件

全体目標は計算資源ハンデ付きOracleへの勝率50%。現在は学習の実行時間を抑えるための
エンジン性能改善とscoreバグ調査の段階である。強化成功や0018勝率を性能改善の開始条件にしない。
2026-10-10の[判断材料](../../references/reversi-ai-current-status.md)と
[0046のscore契約記録](../../references/reversi-ai-exact-score-contract.md)で調査証拠と残条件を確認する。
Godotと新規自己対局schema6の明示設定は深度各1..64・exact0..30を受理する。
既定20への変更は求められていない。設定可能性と本番runの採否・時間予算を区別する。
学習前の自己対局効率を測る選択profileは8/8/8・exact16・turn。固定8局を打ち切らずに計測し、平均180秒を
目標として記録する。nearest-rank P95が300秒に達したら探索改善を検討する。これは効率判断の目安であり、
局のwall上限・受け入れ条件・学習batch全体のwall上限ではない。ハング検出用の1手ごとの応答timeoutは別設定とする。

0035の採否を、既存の全局時間証拠、0044の正確性修正、0045の最小検証に基づいて記録する。
完全読みが間違う再利用は採用しない。深度8の固定棋譜の成功だけで深度12の反例を無視しない。
閾値16を含む再利用全般を、修正と検証が済むまで保留する。

ユーザーは2026-10-06に、8局を各3局へ縮小し、本当に必要な計測条件だけを残すよう指示した。
再検証は12/8/12・exact20のturn/game各3局に固定した。Oracle同士と現行CLIの全局時間は
既に測定済みなので、同じ基準値を取り直す作業は完了条件から外す。

大規模な自己対局/学習batchは起動しない。ユーザーが選んだprofileで、代表的な検証済みTrainedEvaluator artifactを
固定8局の性能測定を行う。現行の全局runnerが8/8/8を表現できないため、測定前にこのprofileを扱えるようにする。
平均が目標から大きく外れる、またはP95が300秒に達した場合は中盤探索の改善を最大3案まで試し、
同じartifact/局面で再測定する。速度目安を超えた局も最後まで実行し、時間だけを理由に打ち切らない。
現状artifactがない場合は、test fixtureで代用せず測定gateを残す。目標に届かない場合は最良の実測結果と
残る差を記録して妥協点を選ぶ。閾値20の本番契約更新は別計画とし、0035を採用完了としない。

## 参照

- `docs/references/reversi-ai-whole-game-0035-results.md` — 既存14report、phase時間、legacy/persistentの制約。
- [PR #251](https://github.com/yoskeoka/reversi-adventure/pull/251) — 0041の時間結果、反例棋譜、完全読みのroot/選択child証拠。
- `0043-reversi-ai-exact-cache-correctness.md` — 全経路の既定turnという安全措置。
- `0044-reversi-ai-exact-cache-correctness-repair.md` — 原因限定修正と小さい回帰。
- [PR #255](https://github.com/yoskeoka/reversi-adventure/pull/255) — 完了した0045計画の履歴、各3局/2条件と最大18Oracle queryの固定契約。
- `docs/specs/reversi-ai.md:651-775` — 全局証拠、exact/選択手、manifest、reset/履歴。
- `tools/reversi-ai-training/reinforcement.py` — productionの設定とCLI identity。
- `0035-reversi-ai-self-play-performance.md`, `0037-reversi-ai-training-method-pilot.md`, `0019-reversi-ai-pattern-reinforcement-cycle.md`。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 既存8局証拠と新しい3局subsetの意味、修正後採否を先に記録する。
- (MODIFY) `docs/references/reversi-ai-whole-game-0035-results.md`, `docs/references/reversi-ai-exact-cache-correctness.md` — 証拠digest、残る制約、設定/予算/採否。
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md`, `0037-reversi-ai-training-method-pilot.md` — 承認された設定と正確性の依存を同期する。
- (NEW, 必要な場合だけ) 採用する閾値/policyのproduction spec/manifest互換更新、または観測した原因に絞る追加最適化計画。
- (DELETE, 完了条件を満たした場合だけ) `docs/exec-plan/todo/0035-reversi-ai-self-play-performance.md` と本計画。

## ブラックボックス契約と作業

1. 既存14reportと0041の完成証拠を元のidentityでoffline検証する。古いOracle全局時間、
   CLIの全局時間、phase/node/cache集計はdigestと条件付きで引用する。
   新binaryとの公平な比較対照は0045の同一binary・各3局turn/gameに限定する。
2. 0044の反例回帰、値と選択手の証明、0045の全3局/条件と抽出Oracle queryを確認する。
   不一致、score契約の未解決差、timeout、未完了があれば再利用を不採用にし、
   既定turnと停止理由を維持する。閾値だけを下げて正確性の問題を解決済みと扱わない。
3. 旧legacy CLIのscore/exactness欠落は制約として残す。診断driverを新作して全履歴を再実行しない。
   局間cacheを残した旧persistentは採用証拠から外す。resetの保証は0039と0043/0045の短いfixtureを使い、
   全深度のpersistent/one-game各8局を追加しない。序盤8rootのコスト診断も今回の必須作業から外す。
4. 修正前後の性能/意味の主張を確認した範囲に限定する。3局の局別時間と平均、exact部分のnodes/時間、
   全局に占める割合を示す。反復なしの小さい時間差を有意な高速化としない。
   序盤コストが大きいことは既存phase証拠で示し、追加測定や最適化を必要以上に拡げない。
5. TrainedEvaluator自己対局の設定を8/8/8・exact16・turnに固定し、候補比較/0018の12/12/12・exact16とは分離する。
   検証済みartifactと固定8局を打ち切らずに測り、全局時間・平均・nearest-rank P95を記録する。
   平均180秒を目標とし、P95の300秒は改善検討の目安とする。超過局も完了まで実行する。
   目標から大きく外れる場合は中盤探索を最大3案まで改善し、各案で正確性と同じ局の経過時間を再確認する。
   per-game効率判断と学習batch総時間は別の値として記録する。後者は学習runの件数/上限を定める計画で決める。
6. 閾値20は0045の実験用設定であり、本番の16の自動変更ではない。
   再利用を本番で有効化する場合も、明示承認とpolicy/CLI/spec/manifestの互換更新を別の実装計画で行う。
   この更新が必要な間は0035を未完了のまま依存へ接続する。
7. 設定/予算が承認され必要な本番互換更新まで済めば0035をcloseoutする。
   新本番manifestは0037 pilot成功と0032の完全game/provenance検証後に0019で凍結する。
   旧停止runや正確性不成立の結果を流用しない。

## 依存関係と順序

- PR #251→0043→0044→0045→本計画のoffline検証/人間判断→必要な本番互換更新→親cleanup。
- 0041の完成結果と反例棋譜は[評価記録](../../references/reversi-ai-exact-threshold-reuse-assessment.md)を参照する。
  固定8局の成功・速度差の制約と、終盤の最善値+4/選択手+2という不一致証拠を保持する。
- 0036のTT正規化、0037の学習方法、0018の強さ受け入れは別の契約。
- 0032は[PR #223](https://github.com/yoskeoka/reversi-adventure/pull/223)で完了し計画を削除済み。
  保存source digestは凍結producer 790209d9のGit blobと一致する。現行sourceとの差だけで未解決の破損としない。
  0019の本番freeze前に元producer/契約で入力を再検証し、その条件でも失敗する場合だけ別計画へ切り出す。
- 本計画にOracle全局、旧CLI全局、深度総当たり、常駐方式総当たり、序盤コスト計測を戻さない。
  新しい疑問に必要な追加計測は、対象・件数・上限を別計画で承認する。

## 検証

- 既存不変report、0044/0045のdigestと成功/失敗の再計算。新旧形式や設定を混同しない。
- 未解決の正確性問題、欠落/不完全証拠から採用や親完了を作らないこと。
- 人間の設定/予算/採否と0019/0037の依存が一致すること。
- applicable offline tests、workflow lint、diff check。長い計測は実行しない。

## Addresses

- N/A

## 0045の測定受領とoffline検証（2026-10-08）

0044はPR #254で修正済み。PR #255の固定6局を人間が実行し、
source/harness 2516a63・固定manifestのoffline verifyが終了code 0で成功した。
旧752 receipt、短い回帰3件、turn/game各3局、抽出6 root/10 Oracle queryと
派生reportを再計算した。全3組の意味一致と全抽出root/選択childの独立一致を確認した。
opening-4は空き16・白0で終局しselectorが存在しないためOracle抽出0件。
0045の測定/検証条件は完了し、計画を削除した。履歴はPR #255を参照する。

平均wallはturn 519.254秒、game 502.221秒。exact部分は51.907秒/50.835秒で、
heuristic nodesは両条件同じ。反復なしのwall差3.28%はcacheによる有意な高速化の証拠にしない。
局別時間・資源・抽出範囲・digestと制約は
[正確性記録](../../references/reversi-ai-exact-cache-correctness.md) を参照する。

本番turn/exact16は維持する。0046で±39/±40の原因をscore契約差として
terminal/root/childまで確認した。ユーザーはEdaxも同じ規則なら統一を希望し、
固定Edax sourceでも勝者への空き加算を確認した。0047で新AI/教師値をOracle/Edax規則へ
移行する。旧証拠は元契約のまま保持し、最新producerの独立root/選択child一致は別に受け入れる。
0046の原因確認だけで本番freeze・正確性gateを解除しない。
設定/時間予算/採否の人間判断、採用時の別計画によるproduction互換更新は未達。
0045完了を再利用の採用・0035の完了と扱わない。

## winner-empty移行後のoffline検証と残gate（2026-10-10）

ブラックボックス契約を先に更新し、旧0035/0041/0045の時間とOracle証拠は元のscore契約のまま保持した。
これらのreceiptをwinner-empty-v1の性能・Oracle一致へ読み替えず、productionは12/12/12、exact16、turnを維持する。

保存済み証拠の再検証はすべてofflineで行った。0035のlegacy registry manifestは14件
（whole-game 10、comparison 2、独立Oracle照合2）が通過した。0041のlegacy exact-threshold manifestも通過した。
0045のexact-cache manifestは、凍結verifierを一時Git展開した時にlauncher内entrypoint pathが変わる問題を修正後、
終了code 0で成功した。6局、10 query、3 regressionはすべて保存済み成功としてskipされ、workloadは追加していない。
修正はmanifest-pinned original entrypointをbyte比較前に復元し、runnerや保存evidenceは変更しない。
空白を含むpathの復元と不一致時の拒否をoffline unit testで確認した。

winner-empty-v1のbounded Rust testは各1件成功した。
`tiny_both_alive_root_child_and_pv_use_independent_winner_empty_score`、
`interruption_after_research_started_discards_exact_attempt`、
`expired_deadline_returns_the_documented_fallback`、
`cancellation_returns_the_documented_fallback`、
`interrupted_before_depth_one_returns_legal_fallback_without_score`。
専用Python test 7件と`make oracle-test`も成功した。これらはroot/選択child/PVの局所意味と
未完了探索時の資源応答を確認するが、外部Oracleの新契約照合や性能証拠ではない。

新契約での外部Oracle root/選択child照合と、検証済みTrainedEvaluator artifactによる8/8/8の性能測定は未実施。
ユーザーは自己対局profileを8/8/8・exact16・turn、平均3分を目標、P95 5分を改善検討の目安に指定した。
この時間は探索エンジンの改善判断に使い、局のhard limitや学習batchの上限にはしない。
runnerの1手ごとの応答timeoutはハング検出の別設定として維持する。
測定に使える検証済みartifactがこのcheckoutにないため、test-only fixtureで時間を代用しない。
全局runnerのphase深度拡張、artifact利用可能性、新契約Oracle照合、実測/必要な中盤改善をactive gateに残す。
設定は0037/0019へ候補profileと区別して同期するが、pilot/freezeの完了とは扱わない。
