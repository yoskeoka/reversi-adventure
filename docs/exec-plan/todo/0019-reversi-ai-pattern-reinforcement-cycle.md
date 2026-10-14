# Child plan: run one bounded pattern-reinforcement cycle

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

> **0047 score移行後の境界**: 新規AI/教師値は `winner-empty-v1`、artifact format2、
> trainer/record schema2、reinforcement manifest6・report4を使用する。旧schema3/4/5完成証拠と
> raw差baseline/validationは明示legacy offline検証だけに保持し、新runへ読み替えない。
> 本番入力の再生成・再学習は件数/上限/進捗/再開を固定した別の人間操作計画で行う。
> [移行記録](../../references/reversi-ai-winner-empty-migration.md)を参照する。
> 0040のreport-pinned producerでの独立root/選択child照合（132 exact positions、252 Oracle queries）・資源観測・
> 人間の性能判断は2026-10-13に完了した（[結果](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md)）。
> 0037 pilot、0019の新契約baseline/validationと候補cycle、0018 held-out受け入れは別の未達gateとして残す。
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
> 0037のpilot成功と0032入力の完全game/provenance検証は引き続き本番freezeの前提とする。
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
runtime search semantics, or add human-facing explanations.

The reinforcement cycle is a human-operated long-running job. A human starts
it in a separate terminal from the generated frozen manifest; an AI agent does
not start, wait for, poll, monitor, or claim completion of that job. A later
task receives only its immutable artifact/report paths and digests, validates
them, and then decides whether 0018 may freeze the candidate.

## Existing references

- `docs/specs/reversi-ai.md:56-145` -- pattern contract and offline trainer.
- `tools/reversi-ai-training/training.py:162-309` -- manifest validation,
  sparse artifact serialization, digesting, and held-out report.
- `tools/reversi-ai-oracle/oracle.py:1161-1275` -- external corpus evaluation.
- `docs/exec-plan/todo/0011-reversi-ai-strength-calibration.md:65-97` --
  candidate profile and vocabulary.
- `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md:1-61` --
  later frozen held-out acceptance boundary.

## Change map

- (MODIFY) `docs/specs/reversi-ai.md` -- self-play input provenance, one-cycle
  update/selection rules, and separation of tuning from acceptance openings.
- (MODIFY) `tools/reversi-ai-training/training.py` and tests -- deterministic
  self-play generation, bounded TD-style outcome update, artifact selection,
  and fail-closed manifest/report validation.
- (NEW) versioned tiny self-play fixture, immutable candidate report schema,
  and Make targets/scripts for the bounded cycle and corpus-regret evidence.
- (MODIFY) `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md`
  -- depend on this candidate-production evidence before freezing acceptance.

## Black-box contract and work

1. Freeze a self-play manifest before any game: source commit, baseline
   artifact digest, evaluator/search profile, exact-solver threshold, book
   mode, game count, pairing/rotation policy, seed, resource cap, and update
   rule. Self-play must use only project-owned binaries and artifacts.
   Document the exact human-run command, output directory, and stop/restart
   behavior. The command writes its report atomically only after a complete
   cycle; partial output is not candidate evidence.
2. Generate legal games with color-swapped and symmetry-rotated pairs. Record
   every game input, terminal score, failure, and digest; a timeout, malformed
   record, or incomplete pair fails the cycle rather than being omitted.
3. Update sparse phase/feature weights from final-disc outcomes with a bounded,
   deterministic TD-style rule. Preserve the 64-feature, 60-phase, `-64..=64`,
   integer-bound, and canonical-artifact contracts. Identical frozen inputs
   reproduce candidate and report digests exactly.
4. Select at most one candidate against the baseline using a validation split
   that is disjoint from self-play tuning records and 0018 openings. The report
   must retain both results and choose the baseline on a tie or failed gate.
5. Run corpus regret under the frozen 0011 profile as evidence only. The 0018
   held-out suite remains unread and unused until it freezes the selected
   artifact and configuration for its own win-rate test.

## Dependencies and sequencing

- 0050 toolingマージ → 0051のwinner-empty入力生成・baseline再学習・Oracle原本保存と
  完成bundleのoffline検証 → 0037の実pilot成功の順で進む。旧0032 raw差入力の検証は
  履歴であり、新契約入力完成の代わりにはしない。bundleとpilotの露出keysに0019の
  学習/評価keysを加えて保存し、候補選定後の0018開局root衝突検査へ渡す。
- 0037の実pilotを、新契約の独立入力と単段階6局/768教師行以下/20比較局で完成させる。
  `pattern-pilot-verify`がraw dataからheld-out誤差改善と他指標の悪化上限を確認した場合だけ、
  0019の新規本番manifestを別directoryで凍結する。
  [ツール実装・fixture検証](../../references/reversi-ai-training-pilot-tooling.md)だけではこの依存を満たさない。
  不成立時はcandidate artifactと結果を保存して方法を再計画する。

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
- Verify that the human-run command documents its output digest and that a
  partial or missing report fails closed without any monitoring loop.
- Validate the selected artifact through `TrainedEvaluator` and run the
  evaluation-only candidate CLI with the frozen configuration.
- Generate the corpus-regret report; confirm it is not an 0018 opening suite.
- Applicable Rust/Python tests, Clippy, workflow lint, and `git diff --check`.

## Addresses

- N/A
