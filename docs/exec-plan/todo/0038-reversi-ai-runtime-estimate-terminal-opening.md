# 0019 runtime estimateが早期終局openingで停止しないようにする

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0019のproduction実行前に計測するOracle runtime estimateが、決定的なopening replayで48石到達前に終局したときも、合法な代表局面を使って3 profileの計測へ進めるようにする。

再現: run `0019-20261020-01` はseed `20261014` で生成した最初のOracle-match opening（`c4 c3 e6 f4 d3 b4`）を使用する。初手から最初の合法手を選ぶ既存の決定的replayでは41石で双方合法手がなくなる。現行処理はこの終局盤面を48石targetの代表局面として追加し、合法手検証で `runtime estimate could not select a legal representative position` を出して止まる。失敗runはmanifestのみで、対局phase開始前に終了した。

完了時には、targetに届いた場合はその合法局面を使い、先に終局した場合はそのreplayで到達した最も進んだ合法局面を使う。終局盤面は計測しない。estimate出力はtarget石数と実測局面の石数を示し、3 profileのOracle/project測定を維持する。実際のOracle-match openingや対局、manifest、評価条件は変更しない。

## 参照

- `docs/specs/reversi-ai.md` — Oracle runtime projectionの代表局面、終局時fallback、実測石数を定義する。
- `tools/reversi-ai-training/production_cycle.py:914-957` — 現行の決定的opening replayと3 profileのruntime estimate。
- `tools/reversi-ai-training/tests/test_pilot.py` — production-cycleの回帰テストを置くPython test module。
- `docs/references/reversi-ai-winner-empty-input-run.md` — 0051の検証済みinput bundleを0019が使う境界。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 48石target未達の時に終局盤面を選ばないこと、最後の合法局面へのfallback、requested/actual occupied countの診断出力を規定する。
- (MODIFY) `tools/reversi-ai-training/production_cycle.py` — runtime representative選択を合法局面だけに限定し、targetと実測石数を返す。
- (MODIFY) `tools/reversi-ai-training/tests/test_pilot.py` — seed `20261014` の最初のOracle openingで41石終局を再現し、late-game測定が最後の合法局面を使い終局盤面を使わないことを確認する。

## ブラックボックス契約と作業

1. 仕様のruntime estimate契約に従い、既定のopening、30石midgame target、48石late-game targetを保持する。target前に終局した時は、openingから到達した中で最も石数が多く、手番側に合法手がある局面へfallbackする。fallbackでも合法局面を得られなければ、Oracle/project searchを起動する前に明確なエラーを返す。
2. 各代表計測にrequested occupied countとactual occupied countを出力する。fallback時にも3 profileを計測し、phase labelを保持する。
3. 対象openingを純粋なunit-level regressionで再生し、terminal positionが候補に含まれないこと、fallback positionの手番側に合法手があること、actual countが48未満であることを検証する。通常通りtargetへ到達する場合もexact target positionを選ぶ。
4. 0019のmanifest、Oracle-match開局、対局/評価設定、入力bundle、immutable run evidenceの意味を変えない。失敗済み`0019-20261020-01`は保持し、新しいsource commitでは新しいrun rootを使う。

## 依存関係と順序

- 0038計画PRのmerge後、fresh `fix/0038-reversi-ai-runtime-estimate-terminal-opening` worktreeを最新mainから作って実装する。
- まず`docs/specs/reversi-ai.md`の契約を実装branchへ反映し、その後にhelperとunit testを変更する。
- 修正のmerge後、人間が新しいrun rootで0019を再実行する。実行は人間操作であり、agentは起動・待機・poll・監視しない。

## 検証

- `python3 -m unittest discover -s tools/reversi-ai-training/tests`を実行する。
- 該当するworkflow lintと`git diff --check`を通す。
- 回帰テストで早期終局openingのfallbackと通常のtarget到達の両方を確認する。Oracle binaryや候補CLIを使った長時間production runはこの修正の自動検証に含めない。

## Addresses

- N/A — 既存Issueに紐づかない実行時不具合。
