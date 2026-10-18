# 学習pipelineの小規模pilotを完走・検証する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

> **2026-10-14実装境界（当時の状態）**: 新契約の本番入力がなかったため、pilot専用prepare/run/verify、一次資料調査、fixtureでの検証を先行した。
> 実入力とbaselineは0051で生成・独立検証済み（[run記録](../../references/reversi-ai-winner-empty-input-run.md)）。
> 0037の人間操作6局/20比較局、完成出力の独立検証は未完了であり、本計画はその完了条件まで残す。
> 入力toolingやbundle完成を「強化を観測」や0019 freezeの許可としない。
> 既存production/legacy producerの意味を変更せず、`pilot.py`から共通helperを再利用する。
> 学習方法と判定基準は[調査記録](../../references/reversi-ai-training-method-review.md)、
> 起動と検証は[README](../../../tools/reversi-ai-training/README.md)を参照する。

> **0047 score移行後の境界**: 新規AI/教師値は `winner-empty-v1`、artifact format2、
> trainer/record schema2、reinforcement manifest6・report4を使用する。旧schema3/4/5完成証拠と
> raw差baseline/validationは明示legacy offline検証だけに保持し、新runへ読み替えない。
> 本番入力の再生成・再学習は件数/上限/進捗/再開を固定した別の人間操作計画で行う。
> [移行記録](../../references/reversi-ai-winner-empty-migration.md)を参照する。
> 0040のreport-pinned producerでの独立root/選択child照合（132 exact positions、252 Oracle queries）・資源観測・
> 人間の性能判断は2026-10-13に完了した（[結果](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md)）。
> 0037 pilot、0019の新契約baseline/validationと候補cycle、0018 held-out受け入れは別の未達gateとして残す。
> strong-engine-hcap-v1の12/12/12・exact16とturn policyは維持し、移行だけでproduction freezeを解除しない。
> 学習前の探索器/対局ハーネスprofileはStrategicEvaluator・8/8/8・exact16・turnで計測済み。
> 平均3.77秒、nearest-rank P95 8.08秒で、当該profileに広い探索最適化を加える根拠はない。
> 局のhard limitやpilot batchのwall上限を定める値ではなく、candidate match/0018の12/12/12も変更しない。
> これはTrainedEvaluator評価コストや学習batch総時間を測っていない。higher thresholdでのgame-scope採否は0035に残る。

> **2026-10-02 performance evidence**: 0035の深度12/8の全局計測は完了し、
> `docs/references/reversi-ai-whole-game-0035-results.md` に検証済み結果を記録した。
> 0040の意味検証と人間の設定/性能判断は完了し、測定profileと結果は上記記録に固定した。
> pilotの学習方法/教師値/実行設定の選択はこの計画の未完了作業として残る。
> 追加計測は0039のパラメータ固定scriptと局単位保存/再開を利用し、既存条件を再測定しない。

> **2026-10-06 correctness prerequisite**: PR #251の反例を受けた0043の停止→0044の修正→
> 0045の12/8/12・exact20・turn/game各3局の縮小検証と0040の人間による設定/性能判断は完了した。
> pilotのexact16/`turn` profileで未解決の不一致は確認されていない。高い閾値やgame-scopeを
> pilotで使う場合は0035で先に評価する。0045は新しい速度基準の総当たりではなく、
> 修正の回帰/実行可能性確認である。本pilotの6局/768行/20比較局の上限は変更しない。

## 目的と完了条件

0047実装後の自己対局設定はschema6で3phase各1..64・exact0..30を明示指定できる。
既定12/12/12・exact16、turn policyと候補比較strong-v1は維持する。
[score契約調査](../../references/reversi-ai-exact-score-contract.md)の残条件と
[0040の設定/性能判断](../../references/reversi-ai-efficiency8-closeout-2026-10-13.md)をpilot前に確認する。
higher exact thresholdでのgame-scope再利用は0035で保留中であり、学習方法が必要とする場合に評価する。
設定可能性を本pilotの完了や本番freezeの承認にしない。

このpilotの主目的は、データ準備・教師値生成・学習・候補比較・offline検証までの一連のpipelineを本番規模の10%以下で一度完走させ、予定した入力と出力を独立に再構成できることを確かめること。小標本で強さの改善を期待したり、本番学習方法の有効性を判定したりしない。更新前後の独立指標と`improvement_observed`は診断情報として記録し、改善が見えなくてもpilot失敗や0019開始blockerとはしない。0019では検証済みproduction bundleからbaseline・manifest・outputを新規に作り、pilot artifactを再利用しない。pilot結果から0018の50%目標達成や統計的な一般化は主張しない。

## 参照

- `docs/specs/reversi-ai.md:57-92,150-235` — pattern 表現、0032 入力、0019 の教師値と選定。
- `tools/reversi-ai-training/random_inputs.py:191-225` — 黒先手の合法 random 対局生成。
- `tools/reversi-ai-training/training.py:162-322` — 入力/分割の検証、重み、report。
- `tools/reversi-ai-training/reinforcement.py:131-155,260-370,430-524` — 旧 color-swap pair、終局差ラベル、更新、候補対戦。
- `docs/references/reversi-ai-random-inputs-0032.md:14-59` — 現行 baseline と独立 validation/held-out の観測値。
- `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md` と `0018-reversi-ai-strong-engine-acceptance.md` — 本番と最終受け入れの境界。
- Egaroucid の公開資料と学習 script: https://www.egaroucid.nyanyan.dev/en/technology/explanation/ と https://github.com/Nyanyan/Egaroucid/tree/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/tools/evaluation
- Edax の公開 source: https://github.com/abulmo/edax-reversi/tree/14f048c05ddfa385b6bf954a9c2905bbe677e9d3/src

## 変更マップ

- (NEW) `docs/references/reversi-ai-training-method-review.md` — Edax/Egaroucid の確認できた公開学習方法、source version、未確認部分、今回の方法と教師値の理由。
- (MODIFY) `docs/specs/reversi-ai.md` — 先に合法な黒先手入力、教師値の意味、色相対化、split、pilot と本番の証拠を定義する。
- (MODIFY) `tools/reversi-ai-training/random_inputs.py`, `training.py`, `reinforcement.py` と関連 tests — 選んだ生成・ラベル・更新方式、独立検証、pilot 設定を実装する。
- (NEW) `tools/reversi-ai-training/pilot.py` と関連 tests — 上記producerの既存helperを使う独立orchestration。
  黒先手の合法opening、単段階10ペア、実更新行の上限、独立指標とoffline verifierはpilotで固定する。
  `random_inputs.py`の新契約入力生成と`training.py`/`reinforcement.py`の教師式・更新helper自体は変更不要。
- (MODIFY) Makefile と `tools/reversi-ai-training/README.md` — 小規模の prepare/run/verify と人間が起動する長時間処理を分ける。
- (NEW) `docs/references/` の pilot report — 失敗例も含め、入力・artifact digest、比較方法、観測値を保存する。
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md` — pilotで確認したpipeline feasibilityを本番batchへ接続し、別のbaseline・manifest・outputを使う依存へ更新する。

## ブラックボックス契約と作業

1. Edax と Egaroucid の source/docs/scripts で確認できる生成方法、学習対象、教師値、色と対称性、データ分割を出典と version 付きで記録する。Egaroucid 公開データのランダム序盤後の AI 対局と最終石差ラベルを区別し、公開資料にない Edax の学習工程を推測で埋めない。Egaroucid/Edax は引き続き Make/scripts/CI の外部ツールとし、Rust/GDExtension/配布物に含めない。
2. 黒先手の標準初期盤面から合法に到達する入力だけを学習対局に使う。旧 `member=1` の色反転途中局面を、別の合法対局や黒白の先後交換として数えない。両色の各局面は手番側視点で同一 pattern 重みを使い、回転/反転の同値性は仕様に従って検証する。学習入力と validation、pilot 比較、0018 の未使用開局を分離する。
3. ランダム合法手による高速な盤面収集と、教師値の生成を別の段階にする。単なる random rollout の最終石差、強い project-owned/oracle 継続対局の最終石差、局面ごとの exact score を混同しない。候補方式を pilot 前に固定し、対象局面・着手・score 視点・oracle version・time/node 上限・timeout と失敗処理を manifest に記録する。残り 30 空きから毎手完全読みする案は、固定した少数局面の独立計測で実行可能性を確認してから採用し、未完了/timeout の score を教師値にしない。
4. pilot manifest に本番規模の分母として自己対局 64 局、教師値の上限 7,680 行、候補比較 200 局を固定し、各上限の 10% を切り捨てた自己対局 6 局、採用する教師値 768 行、比較 20 局を超えない。教師値は重複排除後に実際に更新へ渡す行数で数え、生成量が変動しても verifier が上限超過を拒否する。候補比較は pilot 専用の 10 完全ペア・20 局の単段階契約にし、既存 50/200 局の checkpoint/継続判定を流用しない。manifest は分母・丸め規則・各上限・実数を記録し、report/verifier が照合する。乱数・入力・候補 CLI・artifact・学習規則・更新回数と出力は固定する。全局が完成する前の checkpoint は候補証拠にしない。
5. pilot artifact を baseline と独立 validation/held-out の予測誤差、固定 oracle corpus regret、および未使用の色交替対局で比較する。更新前後の値とサンプル数は診断情報として記録する。事前指定した指標の改善条件を満たす場合だけ`improvement_observed=true`と記録できるが、改善条件の未達はpilotの完走・検証を失敗にせず、本番batchへの進行を止めない。小標本の結果から学習方法の強さや0018の50%目標は判定しない。
   本番batchはpipeline feasibilityの確認後に独立して実施し、0018への進行は0018自身の条件で判断する。検証済み0051 bundleから新baseline/manifest/outputを作成し、0037 candidate artifactは再利用しない。

## 依存関係と順序

- 0050の入力bundle toolingのマージ後、0051で人間が新契約の2560局・baseline・
  独立Oracle原本を生成する。完成bundleのoffline再構成とCLI identity照合を通してから
  bundleをpinした新schemaのpilotをprepareする。旧schemaはtoolingのまま保持する。
- 0018 suiteは候補選定後にfreezeする。現時点は`not-yet-selected`と空keysを明示し、
  架空の予約開局を作らない。bundle/pilotのkind別露出keysを後段0018へ渡す。
- 0035 の全局速度基準と、必要なら 0036 の TT 採否を確定してから pilot の engine/config を凍結する。
- 旧 version-1 run と停止済み version-2 run の部分出力を新 pilot の証拠に流用しない。人間が開始する長時間作業を agent は起動・待機・監視しない。完了した不変出力だけ後から検証する。
- 0037の完了条件は予定上限内でpipelineが完走し、production inputと全出力をoffline再構成できること。
  更新前後の改善指標は診断用で、本番batchへの進行条件ではない。0019は0051の検証済みbundleから
  新しいbaseline/manifest/outputで実施し、0037 candidate artifactは持ち越さない。0018の開始条件は変えない。

## 検証

- 黒先手からの合法再生、分割の独立性、色相対 score、exact/oracle score の一致と timeout fail-closed を確認する。
- pilot が manifest の 64/7,680/200 分母から切り捨てた 6/768/20 上限をすべて守り、単段階 10 ペアの対局数と同じ固定入力の再検証で artifact/report digest が一致する。
- 更新前後の独立指標を raw data から再計算し、結果は診断情報として報告する。`TrainedEvaluator` が artifact を受理することと、固定上限内でoffline再構成できることをpilot完了確認に使う。改善値は完了判定に使わない。
- 該当 Python/Rust テスト、Clippy、GDExtension build、workflow lint、`git diff --check`。

## 実pilotの完了結果

- 0051のproduction bundle（SHA-256 `0996da3c4ecfbcf76eeef2ffd7c84072825af450691085b9b5c41ae4f1a09421`）と
  `bundle-verify/report.json`成功receiptは[run記録](../../references/reversi-ai-winner-empty-input-run.md)に固定した。
  train/validation/held-out、baseline、Oracle corpus/golden、CLIを同じbundleから取得する。
  0018予約は未選定・空keysのまま維持する。
- 人間操作run `0037-20261018-01` はreport
  `2ea9ef8c77dc9ee8f2dae385a238dfa2aac37577ec3c30d382e197b515f1a29e` をoffline検証し、
  6 self-play games/326 teacher rows/20 comparison games/12 corpus positionsを完了した。
  elapsedは991.8秒で、pilotの目的であるend-to-end pipelineの実行・再構成を確認した。
- `improvement_observed=false`は小標本で改善を確認しなかった診断結果として保持する。
  pilotの失敗や0019開始blockerを意味せず、0037 candidate artifactは0019へ持ち越さない。
- 0019では検証済み0051 bundleを使い、独立した新baseline・manifest・outputを準備する。
- fixture結果は[ツール検証記録](../../references/reversi-ai-training-pilot-tooling.md)へ記録し、実pilot結果と区別する。

## Addresses

- N/A
