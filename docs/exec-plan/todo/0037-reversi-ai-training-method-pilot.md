# 学習方法を再検討し小規模な強化実績を作る

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

> **2026-10-02 performance evidence**: 0035の深度12/8の全局計測は完了し、
> `docs/references/reversi-ai-whole-game-0035-results.md` に検証済み結果を記録した。
> pilotの実行設定は0040の意味検証と人間の設定/時間予算判断後に固定する。
> 追加計測は0039のパラメータ固定scriptと局単位保存/再開を利用し、既存条件を再測定しない。

## 目的と完了条件

学習データの生成方法と教師値を明示して選び、0019 の本格的な再実行より先に、予定規模の 10% 以下の小規模 batch で `TrainedEvaluator` の更新前後を独立に比べる。改善が観測された artifact、全入力/設定の digest、検証結果を残す。改善しなければ失敗結果を保存し、方法を再計画する。小規模結果から 0018 の 50% 目標達成や統計的な一般化は主張しない。

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
- (MODIFY) Makefile と `tools/reversi-ai-training/README.md` — 小規模の prepare/run/verify と人間が起動する長時間処理を分ける。
- (NEW) `docs/references/` の pilot report — 失敗例も含め、入力・artifact digest、比較方法、観測値を保存する。
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md` — pilot 成功後にのみ新たな本番 manifest を凍結する依存へ更新する。

## ブラックボックス契約と作業

1. Edax と Egaroucid の source/docs/scripts で確認できる生成方法、学習対象、教師値、色と対称性、データ分割を出典と version 付きで記録する。Egaroucid 公開データのランダム序盤後の AI 対局と最終石差ラベルを区別し、公開資料にない Edax の学習工程を推測で埋めない。Egaroucid/Edax は引き続き Make/scripts/CI の外部ツールとし、Rust/GDExtension/配布物に含めない。
2. 黒先手の標準初期盤面から合法に到達する入力だけを学習対局に使う。旧 `member=1` の色反転途中局面を、別の合法対局や黒白の先後交換として数えない。両色の各局面は手番側視点で同一 pattern 重みを使い、回転/反転の同値性は仕様に従って検証する。学習入力と validation、pilot 比較、0018 の未使用開局を分離する。
3. ランダム合法手による高速な盤面収集と、教師値の生成を別の段階にする。単なる random rollout の最終石差、強い project-owned/oracle 継続対局の最終石差、局面ごとの exact score を混同しない。候補方式を pilot 前に固定し、対象局面・着手・score 視点・oracle version・time/node 上限・timeout と失敗処理を manifest に記録する。残り 30 空きから毎手完全読みする案は、固定した少数局面の独立計測で実行可能性を確認してから採用し、未完了/timeout の score を教師値にしない。
4. pilot manifest に本番規模の分母として自己対局 64 局、教師値の上限 7,680 行、候補比較 200 局を固定し、各上限の 10% を切り捨てた自己対局 6 局、採用する教師値 768 行、比較 20 局を超えない。教師値は重複排除後に実際に更新へ渡す行数で数え、生成量が変動しても verifier が上限超過を拒否する。候補比較は pilot 専用の 10 完全ペア・20 局の単段階契約にし、既存 50/200 局の checkpoint/継続判定を流用しない。manifest は分母・丸め規則・各上限・実数を記録し、report/verifier が照合する。乱数・入力・候補 CLI・artifact・学習規則・更新回数と出力は固定する。全局が完成する前の checkpoint は候補証拠にしない。
5. pilot artifact を baseline と独立 validation/held-out の予測誤差、固定 oracle corpus regret、および未使用の色交替対局で比較する。更新前後の値とサンプル数をすべて記録し、少なくとも一つの事前指定した独立指標で改善し、他指標に重大な悪化がない場合だけ「この pilot では強化を観測」と記す。達しないときは artifact と不成立結果を保存し、0018 や本番サイズへの移行を行わない。

## 依存関係と順序

- 0035 の全局速度基準と、必要なら 0036 の TT 採否を確定してから pilot の engine/config を凍結する。
- 旧 version-1 run と停止済み version-2 run の部分出力を新 pilot の証拠に流用しない。人間が開始する長時間作業を agent は起動・待機・監視しない。完了した不変出力だけ後から検証する。
- pilot が独立指標で成功した場合に限り、0019 の大規模 batch を別の新しい manifest で準備する。

## 検証

- 黒先手からの合法再生、分割の独立性、色相対 score、exact/oracle score の一致と timeout fail-closed を確認する。
- pilot が manifest の 64/7,680/200 分母から切り捨てた 6/768/20 上限をすべて守り、単段階 10 ペアの対局数と同じ固定入力の再検証で artifact/report digest が一致する。
- 更新前後の独立指標を raw data から再計算し、`TrainedEvaluator` が artifact を受理する。
- 該当 Python/Rust テスト、Clippy、GDExtension build、workflow lint、`git diff --check`。

## Addresses

- N/A
