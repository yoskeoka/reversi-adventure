# efficiency8 中断後の安全な再開

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0040 の closeout script が中断後に同じ出力先から再開できるようにする。今回の再実行は、既存の `run-identity.json` と測定成果物に記録されたホストの `system` だけが Linux kernel release の違いを含み、それ以外の実測入力は一致していた。再開では検証済みのゲーム、Oracle query、checkpoint を再利用し、未実施分だけを続ける。

同じ node・machine・Linux platform の kernel release 差だけを再開時に許容する。修正のマージで source revision と harness digest が変わるため、以前の closeout runner が生成した保存済みidentityから、明示してサポートする形式だけを移行できるようにする。その場合も保存済みidentityとCLI、profile、openings、score contract、Oracle binary/resource、output directory、game report、checkpointは引き続き検証する。互換性のない runner format、別のソース系統、その他の入力差、破損証拠は従来どおり拒否する。保存済みidentityと完了済み測定値は上書きしない。

Oracle checkpoint と最終evidenceにはqueryごとの実行hostを残す。旧checkpointの実行hostは保存済みrun identityから復元し、再開後のqueryには再開時のhostを記録する。これによりkernelをまたいだ証跡でも、どのqueryがどのkernelで実行されたかを検証できる。実測を打ち切る時間上限は追加せず、Oracle solveも起動しない。

完了条件は、PRマージ後、今回の既存出力先でrunnerがidentity mismatchを起こさず、完了済みcheckpointを検証・skipし、未完了queryから進められること。ローカルでは再現可能なfixture/stubだけでこの再開動作と互換性拒否を検証する。人間が行う実測再開と0040の性能判断はこの計画の完了範囲外とする。

## 参照

- `docs/specs/reversi-ai.md:849-888` — 0040一括closeoutの入力pinning、stage再利用、Oracle checkpoint、failure boundary。
- `tools/reversi-ai-benchmark/run-efficiency8-closeout.py:108-180` — build receipt、run identity、既存identity一致判定。
- `tools/reversi-ai-benchmark/run-efficiency8-closeout.py:183-245` — output validationと `StageTracker` の永続状態。
- `tools/reversi-ai-benchmark/run-efficiency8-closeout.py:405-535` — closeoutのpreflight、build、再利用、self-play/Oracle stageの実行。
- `tools/reversi-ai-benchmark/whole_game.py:946-1085` — Oracle query checkpointのidentity検証、保存、再利用。
- `tools/reversi-ai-benchmark/whole_game.py:1125-1215` — Oracle evidence/checkpointのoffline検証。
- `tools/reversi-ai-benchmark/test_efficiency8_closeout.py:1-190` — 実測プロセスを起動しないcloseout orchestration tests。
- `tools/reversi-ai-benchmark/test_whole_game.py` — Oracle checkpoint/evidenceのunit coverage。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — kernel-only resume compatibility、旧runner artifactの限定移行、per-query execution host provenanceを定義する。
- (MODIFY) `tools/reversi-ai-benchmark/run-efficiency8-closeout.py` — 保存済みの互換runner identity/revision/build receiptを検証して維持し、kernel releaseだけ異なる同一Linux hostから再開できるようにする。stage/final artifactにはinvocation host履歴を加える。
- (MODIFY) `tools/reversi-ai-benchmark/whole_game.py` — Oracle checkpoint/evidenceへquery単位のexecution hostを保存し、旧checkpointを保存identityのhost情報で移行・検証する。
- (MODIFY) `tools/reversi-ai-benchmark/test_efficiency8_closeout.py` — 旧run identity、既存build receipt、kernel-only差分、skipされた完了stage、互換性のない差分をfixtureで検証する。
- (MODIFY) `tools/reversi-ai-benchmark/test_whole_game.py` — 旧checkpoint migration、混在kernelのquery host attribution、schema/digest検証を追加する。

## 実装タスク

1. 仕様にresume境界を記録する。kernel release以外のhost identityの差、CLI/Oracle/openings/settings/report/checkpointの差、壊れたdigestは再開を拒否する。過去の対応runner formatはバージョンを明示した互換migrationだけを許可し、保存済みのproducer identityを維持する。
2. runnerのidentity/build処理を改め、既存の対応済みrunでは保存済みrevisionとbuild receiptを再利用する。新しいrunは現行revisionで通常どおりpinする。source revision lineageと対応runner formatを検証し、任意の古い/別系統のrunへの一般的な緩和にはしない。
3. Oracle checkpointの保存形式をversionし、各queryに実行host/kernel情報を付与する。旧形式のqueryは保存済みrun identityのhostを割り当てた上で再利用し、新規queryは現在のhostで記録する。生成evidence/summaryのdigestとoffline verifierも更新する。
4. stub/fixture testsで、保存済みゲームと85件相当の完了queryを再実行しないこと、未完了queryのみを続行すること、異なるbinary/resource/profile/node/machineや破損証拠を拒否することを確認する。未対応runner formatとcurrent revisionの非祖先であるsaved revisionも、測定process起動前に拒否する。
5. 適用可能なPython test、benchmark workflow/lint、diff checkを実行する。実Oracleや実測は起動しない。計画ファイルをimplementation PRから削除し、`review-task`で最新headを確認する。

## 依存と並列性

タスク1から順に仕様、runner、checkpoint schema、testsを進める。evidenceの形式変更と互換migrationが依存しているため、実装タスクは並列化しない。

## 検証

- 同じhostのkernel releaseだけ異なるpartial-run fixtureから再開し、completed workをOracle/self-play stubが再実行しない。
- 旧producer revision/build receiptを維持して既存whole-game reportを検証でき、final summaryが元reportとrun identity digestを保持する。
- 旧Oracle checkpointの既存queryに元host、新しく実行したqueryに現在hostが割り当てられ、生成evidence/checkpointがoffline verifierを通る。
- node、machine、Linux platform suffix、Oracle binary/resource、CLI digest、settings、opening corpus、report digestの差ではfail closedする。
- 未対応runner format、current revisionの非祖先であるsaved revision、または不正なrun/checkpoint digestは、Oracle/CLI process起動前にfail closedする。
- repositoryの該当Python test、適用可能なlint/workflow gate、`git diff --check` を通す。長時間の自己対局/Oracle計測を実行しない。

## Addresses

- N/A
