# 対戦結果で強化候補を選ぶ

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0019 の自己対局で候補重みを作り、同じ探索条件のベースラインと候補を、学習に使わない別の開局から交互の色で対戦させる。候補の選択は対戦成績で決める。0018 の制限付き外部 oracle に対する勝率目標は別の最終判定として維持する。

学習手法・探索設定・対戦条件・リソース上限と実際の全対局を記録する。同じ source commit、初期乱数、生成局面を再現できることは合否条件にしない。独立に生成した対局に同じ盤面が現れても自己対局を失敗させない。既に失敗した version-1 manifest と成果物を候補とみなさない。

完了には、新契約を実装した PR と、人間が別ターミナルで実行した完結した生産 run の独立検証が必要。AI は長時間 run を開始・待機・監視しない。

## 現状の参照

- `docs/specs/reversi-ai.md:105-230` -- 学習入力、重複禁止、0019 の MSE 選択、source/seed 固定。
- `tools/reversi-ai-training/reinforcement.py:137-210` -- 開局生成と version-1 manifest の厳密な source/seed 検証。
- `tools/reversi-ai-training/reinforcement.py:231-353` -- 候補 CLI、合法対局、再生、検証入力の重複検出。
- `tools/reversi-ai-training/reinforcement.py:360-535` -- 更新、MSE 選択、run と独立 verifier。
- `tools/reversi-ai-training/random_inputs.py:149-215` と `training.py:192-265` -- 完了済み 0032 baseline の生成・検証。今回の 0019 候補選択には再生成を要求しない。
- `tools/reversi-ai-training/tests/test_reinforcement.py:20-195` -- tiny fixture と version-1 検証。
- `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md:1-110` -- 現在の実行計画。
- `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md:1-95` -- 外部 oracle に対する最終目標。
- PR #226 (`https://github.com/yoskeoka/reversi-adventure/pull/226`) は旧重複エラーを早く出す draft。重複を正常に扱う本計画で置き換える。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` -- 手法・条件と標本の区別、候補対戦、最終受け入れの関係を先に定義する。
- (MODIFY) `tools/reversi-ai-training/reinforcement.py` と tests -- version-2 run、独立したベースライン対候補の対戦、対戦選択、結果検証。
- (MODIFY) `Makefile` と `tools/reversi-ai-training/README.md` -- 新しい prepare/run/verify と人間向けの再開・失敗手順。
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md` と `0018-reversi-ai-strong-engine-acceptance.md` -- MSE 選択・同一局面禁止・source/seed 同一性の旧条件を置き換え、0018 のハンデ付き oracle 勝率目標を維持する。

## ブラックボックス契約と作業

1. 生産 run の前に、ベースライン artifact の ID、trainer/update-rule version、特徴契約、候補 CLI の実体 digest、12/12/12 の探索深さ、完全読み開始 16 空き、book mode、自己対局数、候補比較の 50/200 局段階、色交替・D4 方針、探索時間/node 上限、プロトコル timeout、全 decision 上限を固定する。source commit は必須の照合キーにしない。バイナリや artifact の digest は実際に比較した条件の識別と破損検出に使う。
2. 生産開局は実行時の独立した乱数列から生成し、その実際の開局・全着手・手番・終局結果を記録する。明示 seed は fixture や診断に利用できるが、生産 default を固定 seed にせず、同じ seed から同じ生成局面を得られることを合否条件にしない。合法性、対局件数、ペアリング、リソース上限は引き続き検証する。
3. 既存の bounded TD 更新で候補 artifact を作る。旧 `validation.jsonl` を与えた場合は、学習局面と同じ canonical board-and-side の行を MSE 計算から自動除外し、除外 ID と残数を report に記録する。残数が 0 なら MSE を「利用不可」と記録し、run は失敗させない。MSE は候補選択に使わず、検証データを更新にも混ぜない。候補比較の開局は別の乱数列から生成し、学習に現れた開局 root と重なる候補を除外してから、事前宣言した数の完全な色交替ペアを確保する。候補 pool の上限試行数と除外数を記録し、十分なペアを得られなければ比較開始前に失敗する。途中の対局が自然に同じ盤面へ合流しても失敗させない。
4. 同じ候補 CLI、探索設定、リソース上限でベースライン対候補を対戦させる。開局ごとに両色を受け持つペアを作り、先手有利を相殺する。まず完全な 25 ペア、50 局を実施し、候補視点の勝・敗・引分と match points（勝ち 1、引分 0.5）を記録する。50 局時点で候補の match points が 25 を超えたときだけ、同じ条件でさらに 75 ペアを実施し、累計 200 局で最終判定する。25 点以下なら 50 局の完成結果でベースラインを選ぶ。200 局を完了した場合は候補の match points が 100 を超えるときだけ候補を選び、同点以下ならベースラインを選ぶ。失敗または不完了なら結果全体を不成立とし、選択 artifact は公開しない。この選択は標本上の優位であり、0018 の目標達成を主張しない。
5. 50 局の途中結果を原子的な checkpoint として保存し、継続判断とその根拠を示す。200 局へ進んで失敗した場合、checkpoint は診断証拠として残すが選択 artifact にはしない。最終 report は学習と候補比較の全対局・条件・選択理由を含み、最後に原子的に公開する。独立 verifier は記録された対局を合法再生し、候補の更新、50 局判断、200 局判断、対戦勝敗、集計、選択と digest を再計算する。乱数局面の再生成、checkout の clean 状態、HEAD/source commit の一致を要求しない。進捗ログは人間の terminal に出し、report や candidate protocol に混ぜない。
6. 0018 は選択された候補と設定を固定し、独立に用意した未利用の開局で、既存の制限付き oracle profile と対戦する。学習・候補比較に使った開局 root を候補 pool から除外し、必要な完全ペア数を確保してから suite を固定する。`wins / all games >= 0.50`、事前の件数・信頼条件、book/深さ/完全読みのハンデは維持する。0018 の対局結果を 0019 の更新や候補選択に戻さない。異なる対局が途中で同一局面に到達しただけでは失敗させない。

## 依存関係と順序

- この計画がマージされるまで 0019 の次の生産 run は凍結しない。実装は新しい `feat/reversi-ai-reinforcement-match-selection` worktree で、spec を先に更新する。
- 0032 の完成済み baseline artifact は利用できる。既存の version-1 random-input 記録と generator の厳密な再生機能は歴史的証拠として残し、新契約の合否ゲートにはせず、再生成しない。将来、新しい初期 baseline の生成方法も変える場合は別計画で扱う。
- PR #225 の進捗表示を保持する。draft PR #226 の衝突エラー強化をこの実行契約の前提にしない。
- 長時間の自己対局・候補比較は人間が別 terminal で開始する。AI は manifest とコマンドを準備し、完了後の不変出力だけを検証する。

## 検証

- seed を変えた合法な fixture run が異なる開局でも通る。検証行との重複は MSE 対象から除外・計数され、候補比較 opening pool の重複は補充される。途中の偶発的な同一局面では失敗しない。
- 手法・探索条件・artifact/CLI digest の不一致、違法着手、欠けたゲーム、誤った勝敗/集計/選択、部分 report は失敗する。
- 50 局後の停止・200 局への継続、200 局の勝ち越し・同点・負け越し・引分・先後交替を小さな固定対局で検証する。候補とベースラインの同条件、学習更新と候補比較の分離を確認する。
- 旧 0032 baseline を `TrainedEvaluator` と候補 CLI で読み込めることを確認する。tiny fixture で独立 verifier と artifact digest を照合する。
- Python/Rust の該当 tests、Clippy、GDExtension build、workflow lint、`git diff --check` を通す。生産長時間 run はテストゲートにしない。

## Addresses

- N/A
