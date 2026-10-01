# 自己対局性能の証拠を補完して設定を選ぶ

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0035の残る意味一致、常駐時の着手差、序盤探索のコスト、自己対局設定/時間予算の判断を
記録する。既存14レポートを利用し、測定済み条件の8局再実行を既定にしない。
結果が速度目安に届かなければ未達を記録し、人間が現設定の時間予算を受け入れるか、
観測した原因から追加最適化を再計画する。設定選択をagentだけで採用確定しない。

## 参照

- `docs/references/reversi-ai-whole-game-0035-results.md` — 固定入力、局別証拠、phase集計、未解決項目。
- `docs/specs/reversi-ai.md:633-695` — 全局、self_play_search、変更前後の意味一致。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:213-238,310-346` — `choose_move`, stderr診断。
- `tools/reversi-ai-benchmark/whole_game.py:312-327,495-554` — legacy診断欠落、turn/game比較。
- `rust/reversi-ai/src/bin/reversi-ai-search-profile.rs:212-222` — 現profilerは局面ごとfresh engine。
- `rust/reversi-ai/src/eval/trained.rs:152-183`, `search/negascout.rs:209-229` — 既存のcost-diagnostics。
- `rust/reversi-ai/src/cost_diagnostics.rs:1-77` — inclusive countersとtrace。
- `tools/reversi-ai-training/reinforcement.py:684-699` — prepare/run/verify routing。
- `0035-reversi-ai-self-play-performance.md`, `0037-reversi-ai-training-method-pilot.md`,
  `0019-reversi-ai-pattern-reinforcement-cycle.md` — 親計画と学習実行の境界。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 比較context/入力履歴、意味診断、選択した時間予算の契約を先に明示する。
- (NEW) `tools/reversi-ai-benchmark/self_play_closeout.py` と関連tests — 既存reportのphase/共通局面分析、履歴付き意味比較、診断コストの証拠検証。
- (MODIFY) `Makefile`, `docs/references/reversi-ai-whole-game-0035.md` — 0039を使う固定入力scriptのprepare/run/verify手順。
- (MODIFY) `docs/references/reversi-ai-whole-game-0035-results.md` — 補完結果、原因、採否、設定選択とdigest。
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md`, `0037-reversi-ai-training-method-pilot.md` — 設定証拠への依存を同期する。
- (DELETE, 完了時) `docs/exec-plan/todo/0035-reversi-ai-self-play-performance.md` と本計画。
- (NEW, ignored runtime output) 固定パラメータscript、履歴付きsemantic report、opening cost report。

## ブラックボックス契約と作業

1. 0039を先にマージする。既存reportを再検証して局別phase、decision/node数、cache、
   wall/user/system CPU/RSSとdigestの再集計を独立コマンド化する。
   比較する設定/プロセス寿命/入力履歴を必ず列挙する。深度8と12は別workload。
2. legacy/gameは各深度442/408 decisionで着手列一致だが、legacyの点数/exactnessが欠ける。
   PR #236前source revisionを凍結したdiagnostic専用driverを用意し、SearchResultを
   stderr/reportへ取り出す。source差分とdriver digestを保存し、探索/評価コードを変更しない。
   seatごとに当時と同じ要求順を再生してTT履歴を保ち、432/400合法着手のmove/score/depth/
   exactness/outcomeを候補と照合する。旧CLIは10/8 forced pass要求を探索前に返すため、
   そこにsolver呼出しを足して旧履歴を変えない。passは盤面/手番/protocol一致を確認し、
   新CLIの追加pass診断の意味は独立Oracle証拠と回帰テストで別に確認する。
   この意図的な診断追加と比較できない旧値をspec/reportへ明記する。
   単発fresh engineだけで履歴一致を代用しない。
   元binaryの着手列との一致も確認する。診断driverの時間は既存release性能比較に混ぜない。
3. persistent深度8の最初の分岐2位置（opening-1-seat1-turn9、opening-2-seat1-turn3）を
   fixtureに固定し、分岐以前のseat要求履歴付きで再現する。両方の点数/深度は一致しているが、
   それだけで最善手同値と結論しない。通常TT履歴、同点手順序、depth/bound再利用を調べる。
   contextが同じ場合の意味一致と寿命を変えた場合の再現性を区別し、現契約と矛盾するなら
   修正計画を別に作る。仕様を緩めて速度差を採用証拠にしない。
4. opening12がgame8のdecision時間の95.4%を占めるため、既存cost-diagnosticsで
   4開局×両seatの8初期rootを1回ずつ調べる。node上限1,000,000/rootでコスト分類を取り、
   同じnode上限の非診断releaseでoutcome/score/PV/node数/完了depthの対応を検証する。
   非診断releaseにはtraceがないため、trace比較はtraceを出せる診断build間でだけ行う。
   重いrootは完了depthと中断を記録し、
   full-depth速度として報告しない。inclusive countersは重複しており加算して総時間を作らない。
   evaluator/feature extraction/lookup/search/TTのどこが支配的かを観測し、推測と区別する。
   不足なら追加測定数/上限を別計画へ明示し、無制限に拡大しない。
5. 0039のprepareで上記測定のbinary/artifact/source/input digest、上限、条件を埋めたscriptを
   `.local/reversi-ai-whole-game-0035/` に配置する。意味比較は1局の履歴照合ごと、コスト分析は
   1rootごと、Oracle照合は1位置ごとにcheckpointを保存/verify/skipし、未完了単位から再開する。
   長時間測定は人間が1行のscriptで起動する。既存14reportを上書きしない。
6. 選択肢は12/12/12（game約17分/局）と12/8/12（game約6分56秒、persistent約6分34秒/局）。
   Oracle12平均87.8秒を基準に2–3分目安をどう合否値へ固定するか、平均/局別上限、
   学習batch総時間の許容値を提案し人間の判断を記録する。現計測に反復がない0.37/0.61%短縮を
   有意な速度向上と主張しない。完全読みのnode削減と、全局wall差を分けて採用理由を説明する。
   序盤深度を下げる、exact閾値を変える、探索順/評価器を最適化する案は別の変更契約と計画にする。
7. 人間が選んだself_play_search、exact閾値、CLI digest、manifestへ渡す証拠digestを記録する。
   設定/予算が承認され補完検証が通れば0035をcloseoutし、結果文書のactive planリンクも
   削除済みpathへのリンクから実装PR/Git履歴参照に置き換える。追加最適化を選ぶ場合は0035を
   未完了のまま後続計画へ依存させ、完了としない。新本番manifestは0037 pilot成功と0032の
   完全game/provenance検証を満たしてから0019で凍結する。停止済みrunを再利用しない。

## 依存関係と順序

- spec→offline分析/診断driver→0039形式のscript準備→人間の測定→検証→選択判断→親cleanup。
- 0036のTT正規化、0037の教師値/学習方法、0018の勝率受け入れは独立した計画のまま維持する。
- 0032のsource digest mismatchはbenchmark検証を無効化しないが本番freeze前に解決する。

## 検証

- phase集計/共通局面比較、履歴欠落/並び替え、driver探索差分、診断なし/不完了を拒否するfixture。
- 再開後のsemantic集計が連続fixtureと一致し、完成結果のskipが測定を起動しないこと。
- legacyの432/400合法着手の意味比較、10/8 passのprotocol一致と追加診断検証、
  既存独立Oracle138/98位置のreport検証。
- コスト分析の8root/node上限/診断identityを検証。診断CPU時間をrelease時間へ混入させない。
- applicable Rust/Python tests、Rust変更時Clippy/GDExtension build、workflow lint、`rtk git diff --check`。
- 人間の設定/予算/採否記録と0019/0037の依存が一致していること。

## Addresses

- N/A
