# 空き20・24からの完全読みで局内再利用を測る

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

空き16の完全読みは既存8局で約5–8秒しか使わず、再利用で削れる全局時間が小さい。
空き20/24から完全読みする条件を追加し、同じ局内の数手前の読みの再利用が、node数、
wall/CPU/RSS、全局時間へどの程度効くかを測る。中盤深度8/12の多い候補手も局面ごとの
合法手数と時間で確認する。高い閾値が速いことや正確性を事前に仮定しない。
上限内で完了する条件だけを全局測定へ進め、未完了/Oracle不一致も証拠に残す。
本計画の完了は実験の成否と選べる条件の報告であり、production設定の採用は0040で人間が決める。

## 参照

- `docs/specs/reversi-ai.md:633-695` — 16-empty基準、全局の診断/意味比較とself-play設定。
- `tools/reversi-ai-benchmark/whole_game.py:22-24,332-431,514-630` — 固定profile、run/comparison/Oracle照合。
- `rust/reversi-ai/src/config.rs:11-44` — exact閾値とphase。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:213-238` — 完全読みを含むCLI検索。
- `tools/reversi-ai-oracle/oracle.py:177-222` — 固定全局Oracle profile。
- `tools/reversi-ai-training/reinforcement.py:180-195` — 本番self_play_searchは現状exact=16を要求。
- `docs/references/reversi-ai-whole-game-0035-results.md` — 既存基準とraw証拠identity。
- `0039-reversi-ai-whole-game-resumable-measurement.md` — 局reset、固定パラメータscript、checkpoint。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 実験閾値16/20/24、局内だけの再利用、上限と失敗、意味比較の契約を先に追加する。
- (MODIFY) `tools/reversi-ai-benchmark/whole_game.py`, `test_whole_game.py` — 閾値を入力/identity/診断検証/比較に固定し、pilot-windowと全局を区別する。
- (MODIFY) `tools/reversi-ai-benchmark/prepare-whole-game-measurement.py`, `Makefile` — 入力済みscriptとunit別resume/skip。
- (MODIFY) `tools/reversi-ai-oracle/oracle.py` とtests — 20/24-emptyの独立complete solve profileと証拠検証。
- (NEW) `docs/references/reversi-ai-exact-threshold-reuse-assessment.md` — 条件、失敗、測定値、node/合法手数/時間、採用候補とdigest。
- (MODIFY, 採用候補ができた場合) `0040-reversi-ai-self-play-performance-closeout.md` — 追加の設定候補と採用前のproduction契約更新を明記する。
- (NEW, ignored runtime output) `.local/reversi-ai-whole-game-0035/` の新pilot/full manifest、script、局/位置report。

## ブラックボックス契約と作業

1. merged 0039を使い、毎局通常TT/完全読み表をresetする。同じ局の後続rootでだけ
   `game` は完全読み表を保持し、`turn` は手番ごとに完全読み表を消す。heuristic TT条件は同じ。
   source/binary/artifact/openings/host/cache容量/RSS/timeoutを固定し、閾値以外の違いを記録する。
2. 既存game-8棋譜から空き24の合法decision rootを黒2/白2の計4位置、
   opening/assignment/turn順で最初の異なるboard+sideを選んでfreezeする。
   各rootから空き12までの同じ局内windowを測り、閾値16でも後続rootの再利用を観測する。
   空き12以下または合法な終局でwindow完了とする。passは空き数を減らさず履歴に残す。
   pilotのheuristic設定は12/8/12に固定する。pilot成功は実行可能性の事前確認であり、
   full12/12/12の完了や速度を保証しない。
   閾値16/20/24×turn/gameの6条件、各4window（既知total24window）とする。
   各decisionは10,000,000 nodeまたは310秒、peak RSS 1,572,864 KiBをpilot上限とする。
   未完成resultをexactと扱わず、その条件の失敗reportを保存して同じ失敗を自動再測定しない。
3. 同一閾値のturn/gameは同じrootと各seatの履歴を使い、move/score/depth/exactness/outcomeが
   一致することを確認する。閾値間で棋譜や点数が変わることは許容し、別workloadとして報告する。
   根の合法手数、各phase、最初のexact rootとその後のroot別node/cache/時間を残す。
   独立Oracleが新しいexact rootと選択継続をcomplete solveして点数一致を確認する。
   Oracle timeout/未完了は証拠不足として記録し、採用できる成功へ数えない。
4. 閾値ごとにturn/gameの全4windowが完了し独立Oracle照合が通った条件だけを
   深度12/8×turn/game×8全局へ進める（最大6閾値深度組×2scope×8=96局）。
   fullではnode capを外し、従来と同じ310秒/decision、RSS capを固定する。
   新binaryの閾値16をcontrolとして測る。旧binaryの既存reportを新条件としてskipしない。
   0039で新binary同設定の完成controlがある場合は検証して利用する。条件の失敗は保存し、
   成功した局だけを抽出して8局平均や改善率を作らない。
5. 各full条件の8局で比較reportを作り、完全読みのnode/CPU/wall削減、全局wallの割合、
   heuristic8/12の時間と合法手数を報告する。新exact領域を独立Oracleで照合する。
   改善幅が小さければ反復不足を明記し、有意性を主張しない。pilotのnode制限時間を
   full-depth速度と混ぜない。閾値24が失敗して20が成功した場合も両方を報告する。
6. scriptのパラメータをprepareで固定し、人間が1行で起動する。pilotは1window、fullは1局、
   Oracleは1位置が完了単位で、atomic保存→verify→resume/skipを行う。各stage totalはmanifestで
   固定する（pilot=24、fullはgate通過閾値×32局で最大96局、Oracleはsource reportから確定した位置数）。
   stderrは `progress exact-threshold stage=<pilot|full|oracle|verify> threshold=<16|20|24> scope=<turn|game> unit=<window|game|position> done=<n> total=<n> status=<running|saved|skipped|interrupted|verified|failed> elapsed_s=<value>`。
   既定は完成単位ごと、`--progress-every N` は通常進捗を間引き、失敗/中断/完成は必ずflushする。
7. 高い閾値は実験としてreportへ記録する。productionのexact=16制約や0018候補対戦設定を
   この測定だけで変えない。0040で20/24を採用候補にする場合は別のspec/manifest互換更新計画を
   作り、完全読み・資源・学習設定を検証してから本番へ反映する。

## 依存関係と順序

- 0039→実験spec/fixture→固定入力script→人間pilot→gate検証→人間full/Oracle→0040の選択判断。
- 0040のlegacy意味補完や序盤コスト調査は独立に進められる。測定は同一ホストで逐次行う。
- window/rootの対局途中から始めることは明示し、局開始からの全局速度と混同しない。

## 検証

- 小さいexact fixtureで16/20/24 identity、pass、局reset、同じ閾値のturn/game意味一致を確認。
- 閾値の取り違え、pilot未完了のfull扱い、Oracle不足、失敗条件の部分平均、旧binaryのskipを拒否する。
- 局/window/位置ごとの中断再開と完成/失敗skip、raw資源再集計のfixture。
- `rtk make oracle-test`、変更範囲のRust/Python tests、workflow lint、`rtk git diff --check`。
- 長時間測定は人間が起動し、agentは起動/待機/監視しない。

## Addresses

- N/A
