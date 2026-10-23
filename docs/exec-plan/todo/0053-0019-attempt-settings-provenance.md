# 0019の実行設定をattempt単位で記録する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0019の実行前にtimeout・件数・探索上限・seedなどを固定し、phase再開時にもmanifestとの一致を要求する契約を改める。各phase attemptで実際に使う設定を選べるようにし、完了・失敗のどちらでも、そのattemptが実行された時点の設定と完全なexecution commit SHAを証跡へ記録する。設定値を事前に計画や共通manifestへ固定することは完了条件にしない。

Oracle matchがtimeoutで失敗したrun rootから`--resume-from oracle-match`を実行すると、operatorが再実行時に選んだtimeoutを使って新しいattemptを作る。失敗済みattemptとその部分出力は保存される。現在のcheckoutが元runのcommitと異なっていても、実際に使うcommit SHAを記録して実行できる。

既存の`0019-20261020-02` run root（schema version 2 manifest、Oracle以前の成功receipt、`oracle-match/attempt-0001`の失敗記録と完了済み7局）をこの再開経路へ引き継ぐ。旧manifest・receipt・部分出力を書き換えず、検証に成功した前段phaseと完了済みOracle対局は再実行しない。失敗した対局の途中状態は再利用せず、その対局の開始盤面から新しいtimeoutで再試行する。

0019の開始・再開・再試行は引き続き人間が行う。plan branchでは本番対局、Oracle対局、既存`.local/` run rootの変更をしない。

## 参照

- `docs/specs/reversi-ai.md:335-378,1495-1521` — 0019 manifest、phase receipt、resume、実行commitの現行契約。
- `tools/reversi-ai-training/production_cycle.py:355-380` — 成功receiptと失敗recordを作る`write_attempt`。
- `tools/reversi-ai-training/production_cycle.py:980-1049` — `execute`のresume時manifest/config比較、初回manifest作成、predecessor検証。
- `tools/reversi-ai-training/production_cycle.py:594-614` — manifestのmatch設定とdecision timeoutを使うOracle match phase。
- `tools/reversi-ai-training/production_cycle.py:711-755` — Oracle match全局数、opening、decision列を検証する`semantic_phase_check`。
- `tools/reversi-ai-oracle/oracle.py:2299-2401` — 対局順序、完了game record、`on_game`による局単位保存。
- `tools/reversi-ai-training/production_cycle.py:289-298` — manifestのseed/countからphase openingsを再構成する検証。
- `tools/reversi-ai-training/pilot.py:619-690` — execute入口と既定timeoutを含むCLI設定。
- `tools/reversi-ai-training/README.md:490-514` — operator向けretry、manifest、offline checkの案内。
- `Makefile:195-202` — 0019 Make targetからCLIへの設定とresume optionの引き渡し。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 0019のrun identityとphase-attempt設定を分け、各attemptの有効設定とexecution commit SHAを成功・失敗両方で記録するblack-box契約へ変更する。resumeは選択phaseの設定変更や異なるclean commitを許し、再利用するpredecessorは各自のreceipt/output digestと意味検証で確認する。設定変更がpredecessor出力に影響する場合は、その影響を受ける最初のphaseから再実行する。
- (MODIFY) `tools/reversi-ai-training/production_cycle.py` と関連tests — manifestとのtimeout/resource/count/seed等の一律同値比較を除き、phaseごとのeffective settingsと`git rev-parse HEAD`の40桁SHAをattempt provenanceに保存する。receiptまたはfailure recordからprovenanceを検証可能にする。execution commitの欠落・不正形式、汚れたcheckout、attempt provenanceと出力の不一致は高コスト処理開始前またはoffline verificationで拒否する。resumeされたattemptで変えた設定が影響する上流phaseは、そのphaseからの再実行を要求する。既存schema version 2 manifest・receiptを読み込み、digestを保ったまま後続attemptのmetadataを追加できるようにする。
- (MODIFY) `tools/reversi-ai-training/production_cycle.py`, `tools/reversi-ai-oracle/oracle.py` と関連tests — Oracle match retryで直前attemptの`games.jsonl`にある連続した完了局prefixを検証して引き継ぎ、global game/pair/member番号を保ったまま次の未完了局から対局する。旧attemptは変更せず、新attemptは引き継いだ局と追加局を含む完全なgame list/reportを作る。各game recordを出したattemptのcommit SHA・effective settings・input identitiesを別のprovenance recordで追跡し、異なるtimeoutで実行した局を混同しない。
- (MODIFY) `tools/reversi-ai-training/pilot.py` — timeoutを固定run設定として扱う引数配線を見直し、operatorが各実行時に選んだ値を対象phaseへ渡す。数値をplan/specに固定せず、既存の入力妥当性制約は維持する。
- (MODIFY) `Makefile` と `tools/reversi-ai-training/README.md` — resumeコマンドでtimeout等の実行時設定を上書きできること、各attemptの設定とcommit SHAがrun artifactへ記録されること、設定変更時の再開phase選択を説明する。
- (MODIFY) `tools/reversi-ai-training` と`tools/reversi-ai-oracle`のproduction-cycle tests — 変更timeout・異なるclean commitで同じrun rootから再試行できること、失敗attemptを含む各attemptに設定/commitが記録されること、既存predecessor検証と上流依存の再実行境界が保たれることを確認する。Oracle retryは完了済みgame prefixだけを引き継ぎ、失敗局を最初から再試行する。

## ブラックボックス契約と作業

1. 0019のverified bundle、candidate executable、Oracle executable等の入力identityと各phaseのeffective settingsを区別する。入力identity・出力digest・phase間依存は証跡で検証する。timeout、探索資源、progress interval、seedや件数のようなoperator設定は、実行時に指定された値を使い、元manifestに記録された値との一致をresumeの条件にしない。
2. attempt開始時に、そのattemptのphase名、resume元、effective settings、依存するinput/predecessor receipt digest、完全な`git rev-parse HEAD`値を記録する。commit SHAは40桁のlowercase hexで必須とし、source checkoutがdirtyならcommitだけでは再現できないため高コスト処理を始めずに拒否する。完了時のreceiptまたは失敗時のfailure recordからattempt metadataを検証でき、既存の部分出力やfailed attemptを上書きしない。
3. `--resume-from PHASE`は新しいattemptを作り、そのphaseと後続phaseに今回指定された設定を適用する。前段phaseの成功出力は、当該出力を作ったattemptの設定・commitとreceipt digestを基に再検証する。変更設定が保持済みpredecessorの生成に必要だった場合は、そのpredecessorを作る最初のphaseまでresume位置を戻す。設定変更を理由に既存の証跡を読み替えたり削除したりしない。
4. Oracle timeoutを変更したresumeは、同じrun root、同じverified input identitiesから`oracle-match`の新attemptを作れる。旧attemptの`failure.json`と`games.jsonl`を保持し、新しいattemptのprovenanceは選択されたtimeoutと実行commitを示す。timeoutの値自体をspecやplanで固定しない。
   直前のfailed attemptから、profile、開局、candidate/Oracle executable identity、game digestを照合できた完了局だけを新attemptへ引き継ぐ。引き継いだ各局には元attemptのprovenanceを対応付ける。新timeoutは最初の未完了局から使い、timeoutで中断した局は局の最初からやり直す。
   `0019-20261020-02`ではOracle以前のphase receiptとOracle matchの完了7局を検証して再利用し、失敗した`oracle-match/attempt-0001`をそのまま保持したまま新attemptを追加する。旧attemptに個別provenanceがないschema version 2 runでは、元manifestのexecution commit/settingsと固定input identitiesを各局の来歴として扱う。既存manifest・receipt・部分出力は移行のために書き換えない。prefixの欠落、重複、順序違い、identity不一致、game検証失敗があればその局以降を引き継がず、安全に再実行できる位置を選ぶ。
5. offline verificationは、成功した各phaseのreceiptに記録されたeffective settingsとcommit、局ごとのOracle provenanceを最終reportで参照可能にし、run全体を一つのcommit/settingsだったかのように扱わない。失敗attemptのmetadataも改変検出可能にする。
6. operator READMEには変更timeoutでのOracle phase再開例と、検証済み完了局から再開する境界を載せる。実行例は実際の絶対pathと既存run rootを使い、agentは人間操作runを起動・待機・監視しない。

## 依存関係と順序

1. 先にblack-box契約を`docs/specs/reversi-ai.md`へ反映する。
2. manifest / phase context / attempt receipt / offline verificationの順で実装し、各phaseに有効な設定を明示して渡す。
3. resumeの回帰テストとoperator文書を更新し、既存の成功receipt・失敗attemptの保持、predecessor検証、report公開条件を確認する。
4. 新しいrunを起動せずに検証を完了し、plan branchのPRを作る。merge後、対応する`fix/0019-attempt-settings-provenance` worktreeで実装する。

## 検証

- unit/fixture testsで、初回manifest値と異なるtimeoutでのresume、resume commit SHAの変更、変更した設定と関係しないpredecessorの再利用を確認する。
- schema version 2 manifestと既存成功receipt、Oracle matchのfailed attemptをfixtureとして再開し、manifest digest・既存ファイルが不変のままOracle attemptだけを追加できることを確認する。改変・不正なpredecessorは従来どおりfail closedにする。
- Oracle matchのfixtureに7局の完了prefixと次の局のtimeout failureを用意し、7局を再実行せず新timeoutのattemptで未完了局から続けること、再度失敗しても最新完了prefixを次回に引き継げることを確認する。最終match reportは全20局をopening順に含み、各局の実行commit・timeoutとdigestを追跡できる。
- failed attemptにもphase設定と完全なexecution commit SHAが記録され、書き換え・欠落・不正SHA・dirty checkoutが拒否されることを確認する。
- upstream出力に影響する設定変更は最初の依存phaseから再実行され、古い後続phaseの結果と混在しないことを確認する。
- offline verificationがphaseごとの設定/commit provenance、各receipt digest、最終reportを独立に照合することを確認する。
- 該当Python tests、`git diff --check`、workflow lintを実施する。Oracleや本番対局を含む長時間runは起動しない。

## Addresses

- N/A
