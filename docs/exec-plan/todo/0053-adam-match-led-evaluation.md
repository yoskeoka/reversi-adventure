# Adam候補を対戦成績で評価し、既存runを再学習なしで再評価する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

0052のAdam候補はvalidation MSEが採用済みbaselineよりわずかに高く、現行gateが対戦を `not-run` にした。しかしvalidation MSEは予測スコアの近さであり、対戦強度の判定そのものではない。今後はMSEを診断値として報告し、baselineとの対戦成績を強度判定の主指標にする。

baselineとの対戦をまず20局行い、candidateの `wins + draws / 2` が10点以上なら、同じattemptで合計200局まで継続する。20局で10点未満ならそこで止める。200局完了時に100点を超えた場合をbaselineより強い結果とする。ちょうど100点は同等であり、強いとは判定しない。

200局でbaselineを上回った場合、従来と同じOracle identity/profileの20局対戦を診断として実施し、勝敗・引分・match pointsを記録する。Oracle診断は0018受け入れ判定とは分離する。既存candidateを使うevaluation-only入口を追加し、学習を再実行せずに比較を開始できるようにする。元の0052 runは変更せず、新しい評価attempt rootへ記録する。

既存Adam runのepoch選択とearly stoppingは現在のvalidation MSE機構を保つ。変更するのは評価ゲートであり、validation/held-out MSEとcorpus regretは報告・診断に残すが、baseline対戦を止める条件にはしない。candidateの自動採用、0018受け入れ、agentによる長時間対戦の起動・監視は行わない。

完了条件は、新しい評価契約、既存0052候補を指す再評価manifest/receipt、20→200の再開可能な対戦、Oracle診断、独立offline verifier、操作手順とテストが揃い、PRのlatest-head follow-upが完了すること。

## 参照

- `docs/specs/reversi-ai.md:218-280` — frozen optimizer comparisonの現在のvalidation・corpus・match gateとOracle profile。
- `tools/reversi-ai-training/optimizer_compare.py::run, selection` — validation MSEによるepoch選択と、現在のMSE/corpus gateでmatchをskipする流れ。
- `tools/reversi-ai-training/optimizer_compare_matches.py::prepare, run, _reconstruct, verify` — 20局固定の比較、opening生成、candidate/Oracle実行、再構成検証。
- `tools/reversi-ai-training/optimizer_compare_inputs.py` — 0052 manifestとcandidate/source identityの読込み。
- `tools/reversi-ai-training/pilot.py` — `optimizer-compare` command parser/dispatch。
- `tools/reversi-ai-training/README.md` — 0052 prepare/run/verifyの人間操作手順。
- Current source run: `.local/reversi-ai-runs/0052-20261026-01/`; report status is `complete/not-improved`, comparison and Oracle are `not-run`. Candidate artifact SHA-256 is `e77d333d8c3f5591dfa8161e1f2f8acbf393b76ad1172bab670705f2596a56d8`.
- The saved 0052 manifest pins candidate CLI SHA-256 `c50f082c5423ab4cbd60f508d6a7d393211c06dcd6d8bc784ef5add433a76aad`, Oracle SHA-256 `0381e279206317c6d678d066c505afdb9b7d20eda7db62eef6f420c1bf009312`, and the existing 12/12/12 exact16 baseline match profile. Both binaries currently match those identities.

## ブラックボックス契約と作業

1. **spec先行**: optimizer comparisonの採否契約を変更する。MSE/held-out/corpusはreference metricsとして保存し、candidate-vs-baseline 20局を常に開始する。各局のtimeout、opening、candidate/baseline executable、artifact identity、seatをattemptへ固定する。
2. **二段階baseline対戦**: 初回20局は10 opening pairsを座席交換して実行する。match pointsが10/20以上の場合だけ同じ完了prefixから合計200局へ拡大する。100 opening pairsをprepareし、追加180局は初回20局・validation・held-out・teacher・corpus・Oracle openingsと重ならないようにする。200局への拡大はoperator controlとして明示し、初回20局の出力を再計算・上書きしない。
3. **Oracle診断**: baseline 200局が完了し、candidateが100/200を超えた場合、従来と同じ最大20局のOracle対戦を実行する。0019でpinしたEgaroucid 7.8.1 binary/source identityと `oracle-0018-acceptance-v1` profile（6/6/6、exact12、bookなし、1 thread、hash25）を維持し、Oracle openingsは他の全対戦とdisjointにする。reportにはOracleのwin/loss/draw/pointsと比較対象identityを記録する。
4. **既存runのevaluation-only再利用**: `pilot.py optimizer-compare evaluate` 相当の明示的な入口を追加する。入力は完了済み0052 run rootと新規空evaluation root。既存manifest/report/candidate artifact/採用済みbaseline/executable/Oracle identitiesを再検証し、source run digestとcandidate artifact digestを新manifestへ固定する。Adam、teacher生成、epoch selectionは起動しない。既存run report、receipt、artifactを変更しない。必要なartifactやpinned executableが欠ける・digest不一致の場合はfail closedとし、修復または再buildに必要なidentityを説明する。
5. **resumeとimmutable evidence**: 各完成局を原子的に保存する。20局結果は独立receiptに固定し、条件を満たした場合は同一evaluation attemptで180局を追加して200局の総合reportを再構成する。timeout後は同一settings/digestsの完了局prefixから再開し、settings変更時は新attemptを要求する。元runと評価attemptの出力rootを分ける。
6. **offline verification**: 保存済みmanifest、opening、artifact/executable identities、game records、Oracle recordsからreport/gatesを再構成する。verifyはtrainer、candidate CLI、Oracleを起動しない。MSEがbaselineより悪くても対戦が省略されないこと、20局の境界（9.5点は停止、10点は200局へ継続）、200局の境界（100点は非改善、100点超は改善・Oracle実行）、不完全prefixとtamper rejectを検証する。
7. **報告・運用**: reportにvalidation/held-out MSE、corpus diagnostics、20局/200局の勝敗・引分・points、継続条件、Oracle成績、not-run理由、artifactとbinary digestsを記録する。READMEに既存0052 runの再評価コマンド、出力root、timeout/resume controls、operator-only実行境界を追記する。
8. **記録の境界**: 0052の既存reportは歴史的な `not-run` 判定のまま残す。新evaluation reportは新artifactとして記録し、Adam候補の自動採用、0018のaccepted判定、baseline強度の一般化を主張しない。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — optimizer comparisonのMSE/reference、20→200 baseline対戦、Oracle実行条件、evaluation-only/resume/verify契約。
- (MODIFY) `tools/reversi-ai-training/optimizer_compare.py` — pre-match MSE/corpus gateを除き、match-first評価とreport reconstructionを接続。
- (MODIFY) `tools/reversi-ai-training/optimizer_compare_matches.py` — 20/200 opening計画、完了prefix継続、200局後Oracle gate、offline verify。
- (MODIFY) `tools/reversi-ai-training/optimizer_compare_inputs.py`, `tools/reversi-ai-training/pilot.py` — source runからのevaluation-only入力、manifest identity、CLI dispatch。
- (MODIFY) `tools/reversi-ai-training/README.md` —再学習なしの既存candidate評価コマンドと人間操作手順。
- (MODIFY) optimizer comparisonのPython tests — scoring/threshold/resume/immutability/skip gate/Oracle条件を検証。

## 依存・後続

この計画をreview/mergeした後、新しい `feat/0053-adam-match-led-evaluation` worktreeで実装する。現行0052 runのcandidate artifactはそのまま使用できるが、現行CLIでは再評価できないため、新evaluation-only入口の実装が前提となる。長時間の20/200 baseline対戦とOracle対戦はoperatorが開始し、agentは起動・監視しない。

## 検証

- 0052 existing-run fixtureでcandidate artifact/manifest/source report digestsを検証し、evaluation-only preparationがsource runを変更しないこと。
- 不一致・欠損のcandidate artifact、baseline artifact、candidate executable、Oracle binary/profileを拒否すること。
- validation MSEが悪い候補でもbaseline 20局を実行するgate fixture。
- 20局で9.5 points以下なら停止し、10 pointsなら同じattemptに180局追加すること。
- 200局で100 pointsならnot-improved、100超ならimprovedとなり、後者だけOracle 20局を許可すること。
- opening pairsの座席交換、重複/forbidden位置排除、Oracle disjointness、保存prefixのresume、timeout failure preservation。
- offline verifyがtrainer/CLI/Oracle subprocessをspawnしないこと。元0052 reportを含むsource inputsが変更されないこと。
- 該当Python tests、`make lint`または対象lint、`make test`または対象Python suite、workflow lint、`git diff --check`。

## Addresses

- N/A
