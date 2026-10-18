# Child plan: run one bounded pattern-reinforcement cycle

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

> **0047 score移行後の境界**: 新規AI/教師値は `winner-empty-v1`、artifact format2、
> trainer/record schema2、reinforcement manifest6・report4を使用する。旧schema3/4/5完成証拠と
> raw差baseline/validationは明示legacy offline検証だけに保持し、新runへ読み替えない。
> 本番入力の再生成・再学習は件数/上限/進捗/再開を固定した別の人間操作計画で行う。
> [移行記録](../../references/reversi-ai-winner-empty-migration.md)を参照する。
> 0040のreport-pinned producerでの独立root/選択child照合（132 exact positions、252 Oracle queries）・資源観測・
> 人間の性能判断は2026-10-13に完了した（[結果](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md)）。
> 0037実pilotはpipeline feasibilityの確認を目的として完走・再構成済み。小規模結果に改善を期待せず、
> `improvement_observed=false`は診断情報として保持する。
> 0019の新契約baseline/validationと候補cycle、0018 held-out受け入れは別の未達gateとして残す。
> strong-engine-hcap-v1の12/12/12・exact16とturn policyは維持し、移行だけでproduction freezeを解除しない。
> TrainedEvaluator学習前の探索器/対局ハーネスprofileはStrategicEvaluator・8/8/8・exact16・turnで計測済み。
> 平均3.77秒、nearest-rank P95 8.08秒で、当該profileに広い探索最適化を加える根拠はない。
> これはTrainedEvaluator自体や学習batch総時間の測定ではない。candidate match/0018用12/12/12は変更しない。
> higher exact thresholdでのgame-scope採否は0035に残り、学習方法が必要とした場合に判断する。

> **Superseded selection contract**: 0034 implements version-2 method/config recording and baseline-versus-candidate matches. Do not freeze another production run from this version-1 contract. The failed version-1 run is not candidate evidence.

> **New production freeze prerequisite**: 0040's 8/8/8, exact16, `turn`
> whole-game sample and Oracle/resource verification completed; see the
> [closeout record](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md).
> Select and pin the self-play-only midgame depth (12 or 8), exact threshold,
> and accepted CLI digest for the new version-2 manifest. If the selected
> training method requires a higher exact threshold or game-scope reuse, resolve
> that bounded question under 0035 before freezing. Candidate matches and 0018
> retain their separate 12/12/12 search settings. The stopped version-2 run's
> partial files are not candidate or timing evidence; use a fresh manifest and
> output directory.

> **2026-10-02 prerequisite status (historical)**: 当時は0035の14計測レポートは検証済みだが、
> 設定選択と変更前後の点数/exactness確認は未完了だった。0040の補完/採否は上記のとおり完了。
> 0037のpipeline feasibility確認と0032入力の完全game/provenance検証は本番freezeの前提とする。
> 詳細は `docs/references/reversi-ai-whole-game-0035-results.md` を参照。
> プロセスが常駐しても、各局の開始前に通常TT/完全読み表を消去する。局内の読みだけを
> 再利用し、局間cacheを残した旧persistent測定は本番性能の採用証拠にしない。

> **2026-10-06 correctness prerequisite**: PR #251の終盤選択手反例を受けた0043の停止、
> 0044の正確性修正、0045の縮小検証、0040の人間による設定/性能判断は完了した。
> その[closeout記録](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md)はhigher thresholdでの
> game-scope採用を決めていない。学習方法がそれを必要とする場合は0035の評価後にfreezeする。
> 0043実装後の既定は手番ごとにexact tableを消去し、再利用の不一致が未解決のまま新本番runを凍結しない。
> 0045の12/8/12・exact20・各3局は実験用検証であり、本番exact16や学習batch局数を変更しない。
> 再利用や閾値20の本番採用は明示承認とproduction spec/manifest互換更新後にだけ行う。

> **2026-10-18 0037 pilot handoff**: 人間操作run `0037-20261018-01` はreport digest
> `2ea9ef8c77dc9ee8f2dae385a238dfa2aac37577ec3c30d382e197b515f1a29e` でoffline検証済み。
> 小規模pilotの主目的はpipeline feasibilityの確認であり、強さの改善は期待しない。
> `improvement_observed=false`は診断結果として保存し、失敗扱いや0019開始blockerとしない。
> ユーザーは一連の学習・検証pipelineが動くことを確認した上で、独立した0019本番batchへの移行を明示した。
> 0037候補は再利用せず、検証済み0051 bundleから新しいbaseline/manifest/outputで本番batchを実施する。
> 0019自身のvalidation、baseline比較、選択、Oracle距離測定は独立に記録する。

## Objective and completion boundary

> **0047設定契約**: 新規prepare/runはschema6で、自己対局専用3phase深度各1..64・
> exact0..30を独立指定できる。既定12/12/12・exact16、turn policy、候補比較の
> strong-v1固定は維持する。旧schema3/4/5は完成reportの明示legacy offline検証だけに用いる。
> 設定APIの完成から本番freezeを許可しない。[score調査](../../references/reversi-ai-exact-score-contract.md)
> と0040の人間による設定/時間予算/性能判断は[完了済み](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md)。
> 0037 pilotと凍結producerでの入力再検証は本番freezeの前提として残る。学習方法がexact16より高い閾値や
> game-scope再利用を要求する場合は、0035でその条件を別途評価する。

Produce exactly one reproducible, project-owned candidate pattern artifact by
running bounded self-play and updating the existing sparse pattern tables from
game outcomes. Completion records the frozen self-play configuration, inputs,
seed, update rule, candidate and baseline artifact digests, held-out metrics,
and an oracle corpus-regret report. It establishes evidence for a candidate;
it does not tune on 0018's held-out openings, claim the 50% win line, alter
runtime search semantics, or add human-facing explanations. It also records an
unconditional direct match of the raw candidate against 0018's restricted
Oracle profile, even if the candidate loses to baseline or the baseline is
selected.

The reinforcement cycle is a human-operated long-running job, but its
production one-command path is not ready yet. The existing 0037
`tools/reversi-ai-training/pilot.py execute` path prepares, runs, and verifies
the bounded pilot in one invocation. Extend that same script and orchestration
to accept explicit self-play, baseline-comparison, and Oracle-match game
counts, plus an optional phase resume point; do not create a parallel runner
or require a `production` mode switch. Keep the current pilot behavior by
having `pattern-pilot-execute` pass its bounded counts. The new
`pattern-reinforcement-execute` Make target passes the 0019 defaults and lets
the operator override them without editing Python source. The command
consumes the verified 0051 bundle and receipt, freezes all supplied counts in
the manifest, runs input verification, training, selection, corpus regret,
and the unconditional Oracle match, then verifies and publishes the final
report. A resumed invocation must validate its existing manifest and all
preceding phase receipts, and may reuse only complete, phase-verified outputs.
It reruns the selected phase in a new attempt directory. Changed
counts or other frozen settings require a new manifest and run root. The 0051
bundle remains a prerequisite; one production command must not require
separate manual reinforcement prepare/run/verify or Oracle-match commands.
Once implemented, a human starts the full production command; an AI agent does
not start, wait for, poll, monitor, or claim completion of the production run.
Merging this plan PR alone does not make the production run ready to start. A
later task receives only its immutable artifact/report paths and digests,
validates them, and then decides whether 0018 may freeze the candidate.

### Pilot-grounded runtime estimate

The completed 0037 run `0037-20261018-01` has 6 self-play games, 326 teacher
rows, 20 candidate comparison games, and 12 Oracle corpus positions. Its
human-run progress log reported 991.8 seconds elapsed through final offline
verification. Scaling the measured end-to-end time by the 0019 production
denominators (64/6 = 10.67x for self-play and 200/20 = 10x for comparison)
gives an initial core-cycle estimate of 9,918–10,579 seconds (2h45m–2h56m).
This includes pilot-style offline verification, uses game-count scaling, and
is not a runtime guarantee. This projection is for the default 64 self-play
and 200 baseline-comparison games; recompute it from the manifest's supplied
counts whenever either value is overridden.

The estimate excludes the new 20-game match under 0018's restricted Oracle
profile. The 0037 elapsed time does not isolate this candidate-versus-Oracle
pairing at Oracle depth 6/6/6 with exact solving from 12 empties. Before handing
the human-operated command over, estimate that stage from representative
positions under those exact settings and show the projection for the manifest's
Oracle-match game count plus the combined total. The default is 20 games. Do
not present the 2h45m–2h56m core estimate as the total run time.

## Existing references

- `tools/reversi-ai-training/pilot.py:613-712` -- existing `execute` flow,
  arguments, and dispatch to extend with game-count and phase-resume controls.
- `Makefile:121-132,157-183` -- current separate production-stage targets and
  one-command `pattern-pilot-execute` wrapper.
- `docs/specs/reversi-ai.md:56-145` -- pattern contract and offline trainer.
- `tools/reversi-ai-training/training.py:162-309` -- manifest validation,
  sparse artifact serialization, digesting, and held-out report.
- `tools/reversi-ai-oracle/oracle.py:1161-1275` -- external corpus evaluation.
- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:65-97` --
  candidate profile and vocabulary.
- `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md:1-61` --
  later frozen held-out acceptance boundary.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- self-play input provenance, pilot-to-
  production handoff, Oracle distance match, runtime estimate, and separation
  of tuning from acceptance openings.
- (MODIFY) `tools/reversi-ai-training/training.py` and tests -- deterministic
  self-play generation, bounded TD-style outcome update, artifact selection,
  unconditional Oracle match, and fail-closed manifest/report validation.
- (MODIFY) `tools/reversi-ai-oracle/oracle.py`, README, Makefile, and tests --
  the pinned `oracle-0018-acceptance-v1` Oracle profile (6/6/6, exact12), its
  0019 diagnostic match records, and per-stage runtime/progress reporting.
- (MODIFY) `tools/reversi-ai-training/pilot.py`, Makefile, and training README
  -- extend the existing `execute` orchestration with manifest-pinned game
  counts and verified phase resume. Keep `pattern-pilot-execute` on its current
  bounded counts; add `pattern-reinforcement-execute` with overrideable 0019
  count defaults. Reuse the pilot orchestration; do not add a second executor.
- (NEW) versioned tiny production-execute fixture and integration coverage for
  the extended one-command end-to-end path.
- (MODIFY) `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md`
  -- depend on this candidate-production evidence before freezing acceptance.

## Black-box contract and work

1. Extend `tools/reversi-ai-training/pilot.py execute` with required
   `--self-play-games`, `--baseline-comparison-games`, and
   `--oracle-match-games` arguments, plus optional `--resume-from PHASE`.
   `pattern-pilot-execute` passes the existing bounded pilot counts (6 self-play,
   20 baseline-comparison, 0 direct Oracle-match); `pattern-reinforcement-execute`
   passes overrideable Make variables `REINFORCEMENT_SELF_PLAY_GAMES=64`,
   `REINFORCEMENT_COMPARISON_GAMES=200`, and `REINFORCEMENT_ORACLE_GAMES=20`.
   The Make recipe, not a hidden Python constant, supplies these defaults.
   Production requires a positive Oracle-match count. Game counts must
   preserve color-swapped pairs; the manifest records requested and actual
   counts, and every run uses only project-owned binaries and artifacts. One
   new-cycle invocation consumes the
   verified 0051 bundle and receipt and freezes source commit, baseline artifact
   digest, evaluator/search profile, exact-solver threshold, book mode, all
   counts, pairing/rotation policy, seed, resource cap, and update rule in a
   fresh manifest/output root. It then runs input verification, self-play,
   candidate selection, corpus regret, and the unconditional Oracle match
   before offline verification. Document one human-run command, absolute
   paths, count overrides, and resume behavior; it must not require separate
   manual reinforcement prepare/run/verify/Oracle commands.
2. `--resume-from PHASE` names the first phase to execute and accepts only
   `input-verification`, `self-play`, `candidate-update`, `baseline-match`,
   `candidate-selection`, `corpus-regret`, `oracle-match`, or
   `offline-verification`. It resumes only an existing run with an unchanged
   frozen manifest. Verify the manifest digest and every completed
   predecessor-phase receipt/output before continuing; reject missing,
   altered, incomplete, or mismatched evidence. Reuse only complete,
   phase-verified outputs. Write a retry of the selected phase to a new attempt
   directory and preserve failed attempt evidence. Any changed count or other
   frozen setting requires a new manifest and run root; it must not be
   presented as a resume. The report is published only after the full cycle
   verifies, and partial output is not candidate evidence.
3. Generate legal games with color-swapped and symmetry-rotated pairs. Record
   every game input, terminal score, failure, and digest; a timeout, malformed
   record, or incomplete pair fails the cycle rather than being omitted.
4. Update sparse phase/feature weights from final-disc outcomes with a bounded,
   deterministic TD-style rule. Preserve the 64-feature, 60-phase, `-64..=64`,
   integer-bound, and canonical-artifact contracts. Identical frozen inputs
   reproduce candidate and report digests exactly.
5. Select at most one candidate against the baseline using a validation split
   that is disjoint from self-play tuning records and 0018 openings. The report
   must retain both results and choose the baseline on a tie or failed gate.
6. Run corpus regret under the frozen 0011 profile as evidence only. The 0018
   held-out suite remains unread and unused until it freezes the selected
   artifact and configuration for its own win-rate test.
7. Regardless of the baseline comparison or artifact-selection result, play the
   raw updated candidate for the requested number of games (default 20) against
   Egaroucid using the same pair of profiles planned for 0018: Oracle
   `oracle-0018-acceptance-v1` at 6/6/6 with
   exact solving from 12 empties, and the project candidate at 12/12/12 with
   exact solving from 16 empties. Pin both sides' executable/depth/limit
   profiles and verify actual completed depth and exactness for every position.
   Generate one predeclared legal opening per color-swapped pair, bookless
   Oracle, one thread, and hash 25. It measures distance to the goal; it is
   diagnostic only, does not gate 0019 artifact selection, and does not
   replace 0018's final `candidate wins / all games >= 0.50` acceptance test.
   Keep its openings disjoint from all training/selection exposure and from
   0018's held-out suite. Save its opening, decision, and terminal exposure
   keys in the report for 0018's later collision check.
8. Present every Reversi AI match and board/score analysis, including 0037 and
   later 0018 results, with the artifact/opponent,
   sample size, configured opening/midgame/endgame depths, exact-solve threshold
   in remaining empty squares, and the actual per-position completed depth and
   exact flag. Report wins, draws, losses and match points separately.

## Dependencies and sequencing

- 0050 toolingマージ → 0051のwinner-empty入力生成・baseline再学習・Oracle原本保存と
  完成bundleのoffline検証 → 0037実pilotの完了実行とoffline再構成の順で進む。旧0032 raw差入力の検証は
  履歴であり、新契約入力完成の代わりにはしない。bundleとpilotの露出keysに0019の
  学習/評価keysを加えて保存し、候補選定後の0018開局root衝突検査へ渡す。
- 0037の実pilotは検証済み新契約入力で固定上限内の全工程を完了し、raw outputをoffline再構成できた。
  これはpilotの主目的であるpipeline feasibilityの証拠である。小標本に強さの改善は期待せず、
  `improvement_observed=false`は診断情報として保持して本番batchの開始条件にはしない。
  0051 verified bundleからbaselineと新規manifest/outputを使い、pilot artifactは再利用しない。
  [tooling実装・fixture検証](../../references/reversi-ai-training-pilot-tooling.md)だけではproduction inputsや
  run feasibilityの証拠にならず、人間操作pilot reportとoffline verificationが必要。
- 本番の64 self-play games/7,680 teacher rows/200 comparison gamesに対し、
  0037実測elapsed 991.8秒（6/326/20/12）からの線形投影は2h45m–2h56m。
  これは0019本体とpilot形式のoffline verificationの予測値としてcommand handoffに提示する。
  `oracle-0018-acceptance-v1`の20局（Oracle 6/6/6・exact12、candidate 12/12/12・exact16）は含まない。
  このprofileの代表局面を測って20局分のprojectionを算出し、合算した総予測時間も人間run開始前に提示する。

- 0032 is completed in [PR #223](https://github.com/yoskeoka/reversi-adventure/pull/223),
  and its plan was deleted. Revalidation before this freeze belongs to 0019:
  use its frozen producer and original source contract, not current-source
  hashes. Reopen input correctness only if that verification fails.
- Requires the verified project-owned random-game inputs from 0032. Freeze the
  production manifest only after its baseline artifact and separate validation
  JSONL have passed their digest and complete-game verification. Pin their
  exact paths and SHA-256 values; never substitute the tiny fixtures. Keep the
  trainer-held-out set separate from the 0019 validation set.
- Depends on merged 0013/0014 and the 0011 calibration profile.
- Before the human-operated long run, use the completed 0020 series and its
  `docs/references/reversi-ai-search-performance-0020-closeout.md` report. The
  manifest freezes only merged, accepted optimizations; it never runs against
  an experiment branch.
- It may use completed 0017 changes when available, but freezes whichever
  accepted candidate configuration exists at execution time.
- 0018 depends on this plan's recorded selected artifact; it performs the
  separate 50%-win acceptance measurement and triggers a new calibration or
  reinforcement plan if the line is missed.
- The long-running command is explicitly handed to a human. An AI may prepare
  its manifest and validate completed immutable outputs, but must not monitor
  an in-progress reinforcement run.

## Verification

- Unit tests for deterministic pair generation, legal replay, update bounds,
  seed reproducibility, split isolation, and baseline-on-tie selection.
- Run the bounded fixture twice and require byte-identical artifacts/reports.
- Exercise configurable pilot and 0019 count arguments, validate even/pair and
  positive Oracle-match counts, and confirm the supplied values appear in the
  frozen manifest and final report without source edits.
- Exercise fresh-run and `--resume-from PHASE` flows. Accept reuse only when the
  manifest and all predecessor receipts/output digests match; reject changed
  counts, incomplete receipts, and tampered phase output. Verify the selected
  phase is rerun into a new attempt directory and final offline verification
  completes in one command. The real production run remains human-operated.
- Verify that the human-run command documents its output digest and that a
  partial or missing report fails closed without any monitoring loop.
- Validate the selected artifact through `TrainedEvaluator` and run the
  evaluation-only candidate CLI with the frozen configuration.
- Generate the corpus-regret report; confirm it is not an 0018 opening suite.
- Verify the 0018-profile Oracle match runs even when the candidate loses the baseline
  gate or baseline remains selected; replay all requested games (default 20) and reject any
  position with an incomplete required exact solve.
- Verify the frozen human-run summary shows the 2h45m–2h56m core estimate and a
  separately measured Oracle-match estimate plus combined total before the
  human starts the long-running command.
- Check every surfaced match/board/score result includes configured and actual
  search depths and exact-solve settings.
- Verify flushed stderr stage boundaries, root-decision and offline-verification
  formats, `--progress-every` default/validation, per-phase interval behavior,
  forced final updates, and exclusion of diagnostics from immutable artifacts.
- Applicable Rust/Python tests, Clippy, workflow lint, and `git diff --check`.

## Addresses

- N/A
