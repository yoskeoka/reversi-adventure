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
- `tools/reversi-ai-training/training.py:302-322` と `rust/reversi-ai/src/eval/trained.rs:208-235` -- reinforcement artifact の trainer version と provenance 検証。
- `tools/reversi-ai-training/random_inputs.py:149-215` と `training.py:192-265` -- 完了済み 0032 baseline の生成・検証。今回の 0019 候補選択には再生成を要求しない。
- `tools/reversi-ai-training/tests/test_reinforcement.py:20-195` -- tiny fixture と version-1 検証。
- `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md:1-110` -- 現在の実行計画。
- `docs/exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md:1-95` -- 外部 oracle に対する最終目標。
- PR #226 (`https://github.com/yoskeoka/reversi-adventure/pull/226`) は旧重複エラーを早く出す draft。重複を正常に扱う本計画で置き換える。ただし、失敗した局の棋譜と位置をエラーに出す診断要件は本計画に引き継ぐ。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` -- 手法・条件と標本の区別、候補対戦、最終受け入れの関係を先に定義する。
- (MODIFY) `tools/reversi-ai-training/reinforcement.py` と tests -- version-2 run、独立したベースライン対候補の対戦、対戦選択、結果検証。
- (MODIFY) `tools/reversi-ai-training/training.py`、`rust/reversi-ai/src/eval/trained.rs` と tests -- version-2 reinforcement provenance を読み、既存 version-1 artifact の読み取りも保つ。
- (MODIFY) `Makefile` と `tools/reversi-ai-training/README.md` -- 新しい prepare/run/verify と人間向けの再実行・失敗手順。
- (MODIFY) `docs/exec-plan/todo/0019-reversi-ai-pattern-reinforcement-cycle.md` と `0018-reversi-ai-strong-engine-acceptance.md` -- MSE 選択・同一局面禁止・source/seed 同一性の旧条件を置き換え、0018 のハンデ付き oracle 勝率目標を維持する。

## ブラックボックス契約と作業

1. 生産 run の前に、ベースライン artifact の ID、trainer/update-rule version、特徴契約、候補 CLI の実体 digest、12/12/12 の探索深さ、完全読み開始 16 空き、book mode、自己対局数、候補比較の 50/200 局段階、色交替・D4 方針、探索時間/node 上限、プロトコル timeout、全 decision 上限を固定する。source commit は必須の照合キーにしない。バイナリや artifact の digest は実際に比較した条件の識別と破損検出に使う。
   新 run の manifest と report は `schema_version=2` および新しい `producer_version=reversi-ai-pattern-reinforcement-v2` を必須にする。通常の `run` と `verify` は version-1 manifest/report を候補選択の証拠として拒否する。既存 version-1 の baseline weight artifact は入力として引き続き検証・読み取り可能にする。
2. 生産開局は実行時の独立した乱数列から生成し、その実際の開局・全着手・手番・終局結果を記録する。明示 seed は fixture や診断に利用できるが、生産 default を固定 seed にせず、同じ seed から同じ生成局面を得られることを合否条件にしない。合法性、対局件数、ペアリング、リソース上限は引き続き検証する。
3. 既存の bounded TD 更新で候補 artifact を作る。旧 `validation.jsonl` を与えた場合は、学習局面と同じ canonical board-and-side の行を MSE 計算から自動除外し、除外 ID と残数を report に記録する。残数が 0 なら MSE を「利用不可」と記録し、run は失敗させない。MSE は候補選択に使わず、検証データを更新にも混ぜない。候補比較の開局は別の乱数列から生成し、学習に現れた開局 root と重なる候補を除外してから、事前宣言した数の完全な色交替ペアを確保する。候補 pool の上限試行数と除外数を記録し、十分なペアを得られなければ比較開始前に失敗する。途中の対局が自然に同じ盤面へ合流しても失敗させない。
4. 同じ候補 CLI、探索設定、リソース上限でベースライン対候補を対戦させる。開局ごとに両色を受け持つペアを作り、先手有利を相殺する。まず完全な 25 ペア、50 局を実施し、候補視点の勝・敗・引分と match points（勝ち 1、引分 0.5）を記録する。50 局時点で候補の match points が 25 を超えたときだけ、同じ条件でさらに 75 ペアを実施し、累計 200 局で最終判定する。25 点以下なら 50 局の完成結果でベースラインを選ぶ。200 局を完了した場合は候補の match points が 100 を超えるときだけ候補を選び、同点以下ならベースラインを選ぶ。失敗または不完了なら結果全体を不成立とし、選択 artifact は公開しない。この選択は標本上の優位であり、0018 の目標達成を主張しない。
5. 50 局の途中結果を `schema_version=2` と producer version を含む原子的な checkpoint として保存し、継続判断とその根拠を示す。checkpoint は再開データではない。`run` は出力先が存在しないか空である場合だけ開始し、checkpoint・一部の成果物・一時ファイルなどが残る出力先では内容や manifest の一致に関係なく開始前に拒否する。失敗後は既存出力を上書きせず、同じ条件の manifest を使う場合も新しい出力先で自己対局から再実行する。200 局へ進んで失敗した場合、checkpoint は診断証拠として残すが選択 artifact にはしない。最終 report は学習と候補比較の全対局・条件・選択理由を含み、最後に原子的に公開する。独立 verifier は完成出力と checkpoint の manifest identity・digest・50 局成績・継続判断の一致を検証し、古い、壊れた、異なる manifest の checkpoint または checkpoint だけの部分出力を拒否する。記録された対局を合法再生し、候補の更新、50 局判断、200 局判断、対戦勝敗、集計、選択と digest を再計算する。乱数局面の再生成、checkout の clean 状態、HEAD/source commit の一致を要求しない。進捗ログは人間の terminal に出し、report や candidate protocol に混ぜない。
   候補重みの `format_version=1` と特徴契約は維持し、`provenance.trainer_version` を `reversi-ai-pattern-reinforcement-v2` とする。Python/Rust の両 validator はこの新しい producer と `bounded_td_v1` を認め、artifact digest を引き続き検証する。artifact に記録された実際の seed は来歴であり、同じ棋譜の再生成を要求しない。version-1 の重み artifact は従来の検証規則で読み取れるが、version-1 の run report から version-2 の selected candidate を凍結しない。
   `run` と `verify` の失敗は、原因を示す既存のエラー文とともに、manifest path、処理段階、対象を stderr に即時 flush して出す。対局に紐づく失敗では、自己対局・候補比較の種別、1 始まりの局番号/その段階の予定総数、pair/member、opening ID、手数または decision ID、手番・対戦側、開局着手と失敗直前までの着手を `f5d4...` 形式の短い棋譜（pass は `--`）で示す。CLI の timeout・異常終了・不正応答・違法着手、decision/turn 上限、合法再生・終局点数・game digest の不一致を含み、問題の応答があればその値も示す。検証時に記録から局を特定できる場合も同じ文脈を付ける。validation 行・opening pool・artifact・report・公開処理など局に紐づかない失敗は、段階と record ID またはファイル名、可能なら期待値/実際値を示し、架空の局番号を出さない。途中で失敗しても完了 report や選択 artifact は公開せず、診断は checkpoint/report/digest/protocol/stdout に混ぜない。
6. 0018 は選択された候補と設定を固定し、独立に用意した未利用の開局で、既存の制限付き oracle profile と対戦する。学習・候補比較に使った開局 root を候補 pool から除外し、必要な完全ペア数を確保してから suite を固定する。`wins / all games >= 0.50`、事前の件数・信頼条件、book/深さ/完全読みのハンデは維持する。0018 の対局結果を 0019 の更新や候補選択に戻さない。異なる対局が途中で同一局面に到達しただけでは失敗させない。

## 依存関係と順序

- この計画がマージされるまで 0019 の次の生産 run は凍結しない。実装は新しい `feat/reversi-ai-reinforcement-match-selection` worktree で、spec を先に更新する。
- 0032 の完成済み baseline artifact は利用できる。既存の version-1 random-input 記録と generator の厳密な再生機能は歴史的証拠として残し、新契約の合否ゲートにはせず、再生成しない。将来、新しい初期 baseline の生成方法も変える場合は別計画で扱う。
- PR #225 の進捗表示を保持する。draft PR #226 の衝突エラー強化をこの実行契約の前提にしない。
- 長時間の自己対局・候補比較は人間が別 terminal で開始する。AI は manifest とコマンドを準備し、完了後の不変出力だけを検証する。

## 検証

- seed を変えた合法な fixture run が異なる開局でも通る。検証行との重複は MSE 対象から除外・計数され、候補比較 opening pool の重複は補充される。途中の偶発的な同一局面では失敗しない。
- 手法・探索条件・artifact/CLI digest の不一致、違法着手、欠けたゲーム、誤った勝敗/集計/選択、部分 report は失敗する。
- version-1 manifest/report を新しい run/verify が拒否し、version-1 baseline artifact と version-2 候補 artifact を Python/Rust の両方で正しく受理する。version や provenance を偽装した artifact は拒否する。
- 50 局後の停止・200 局への継続、200 局の勝ち越し・同点・負け越し・引分・先後交替を小さな固定対局で検証する。候補とベースラインの同条件、学習更新と候補比較の分離を確認する。
- `run` は既存 checkpoint、一部成果物、一時ファイルがある出力先を再開・上書きせず開始前に拒否し、空の新しい出力先なら最初から実行する。`verify` は checkpoint の digest・manifest identity・50 局の集計/判断が完成出力と一致することを確認し、checkpoint だけの部分出力や不一致を拒否する。
- 自己対局・候補比較・`verify` で局中または記録の検証が失敗する fixture を作り、エラーに manifest、段階、正しい 1 始まりの局番号/総数、pair/member、手数、手番、短い棋譜、元の失敗理由が出ることを確認する。CLI timeout・違法着手・game digest 不一致を代表例にする。validation の不正行など局外の失敗では record ID またはファイル名が出て、局番号を捏造しないことを確認する。失敗時に完成成果物を公開しないことも確認する。
- 旧 0032 baseline を `TrainedEvaluator` と候補 CLI で読み込めることを確認する。tiny fixture で独立 verifier と artifact digest を照合する。
- Python/Rust の該当 tests、Clippy、GDExtension build、workflow lint、`git diff --check` を通す。生産長時間 run はテストゲートにしない。

## Addresses

- N/A
