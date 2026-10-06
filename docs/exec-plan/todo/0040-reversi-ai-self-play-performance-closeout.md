# 正確性修正と縮小検証の結果から自己対局設定を選ぶ

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0035の採否を、既存の全局時間証拠、0044の正確性修正、0045の最小検証に基づいて記録する。
完全読みが間違う再利用は採用しない。深度8の固定棋譜の成功だけで深度12の反例を無視しない。
閾値16を含む再利用全般を、修正と検証が済むまで保留する。

ユーザーは2026-10-06に、8局を各3局へ縮小し、本当に必要な計測条件だけを残すよう指示した。
再検証は12/8/12・exact20のturn/game各3局に固定した。Oracle同士と現行CLIの全局時間は
既に測定済みなので、同じ基準値を取り直す作業は完了条件から外す。

本計画は追加の長い探索を起動せず、証拠のoffline検証と人間の設定/時間予算/採否判断を完了する。
未達なら未達のまま記録する。追加最適化・閾値20の本番契約更新を選んだ場合は別計画へ依存させ、
0035を採用完了としない。

## 参照

- `docs/references/reversi-ai-whole-game-0035-results.md` — 既存14report、phase時間、legacy/persistentの制約。
- [PR #251](https://github.com/yoskeoka/reversi-adventure/pull/251) — 0041の時間結果、反例棋譜、完全読みのroot/選択child証拠。
- `0043-reversi-ai-exact-cache-correctness.md` — 全経路の既定turnという安全措置。
- `0044-reversi-ai-exact-cache-correctness-repair.md` — 原因限定修正と小さい回帰。
- `0045-reversi-ai-exact-cache-correctness-verification.md` — 各3局/2条件と最大18Oracle queryの固定契約。
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
5. 人間が自己対局設定、再利用の採否、平均/局別上限、学習batch総時間の許容値を判断する。
   Oracleの既知速度と2–3分目安、CLIの既知約8分/局を既存証拠として示す。
   速度目安未達なら受容する時間予算か、追加最適化の必要性を明示する。
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
- 0032のsource digest mismatchはbenchmark検証を無効化しないが本番freeze前に解決する。
- 本計画にOracle全局、旧CLI全局、深度総当たり、常駐方式総当たり、序盤コスト計測を戻さない。
  新しい疑問に必要な追加計測は、対象・件数・上限を別計画で承認する。

## 検証

- 既存不変report、0044/0045のdigestと成功/失敗の再計算。新旧形式や設定を混同しない。
- 未解決の正確性問題、欠落/不完全証拠から採用や親完了を作らないこと。
- 人間の設定/予算/採否と0019/0037の依存が一致すること。
- applicable offline tests、workflow lint、diff check。長い計測は実行しない。

## Addresses

- N/A
