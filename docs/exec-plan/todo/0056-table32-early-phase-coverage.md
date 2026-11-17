# 序盤の限られた局面を使った table32 部分学習

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

phase 0–9 を対称性を考慮した実際の局面数に合わせて扱い、既存 10–59 の完成成果と結合可能にする。phase 0 は暫定の評価値 0 とし、学習・強さの検証が済んだ値とは扱わない。少数の局面しかない phase で16種類の独立局面や存在しない検証データを要求しない。検証不能な項目を成功扱いしない。

本計画の実装は仕様、実装、fixture、operator向け新rootの手順まで。実学習・対局・Oracle診断は人間が別途実施する。既存 0–9 の停止結果、10–59 の各原本と結合候補、採用済み 0019 を変更しない。0018受け入れやモデル採用を意味しない。

Addresses: N/A — 既存0054部分実験の有界な回復。

## 根拠と方針

`0054-20261114-phase0-9` は prefix 0 から同じ開始局面で16局生成し、phaseごとのraw行数は train 12 / validation 2 / test 2 だが、canonical重複排除後は各phase train 1 / validation 0 / test 0。結果は `input-coverage-unavailable`、候補なし。同一rootの再実行は結果を再利用する。部分経路は序盤poolを無効化する。

初期局面の canonical 数は1、1手後も1、2手後は3、3手後は14、4手後は60（現行の合法手とcanonical化で到達可能な局面を数えた値）。採用する実装ではこれを再現可能な小規模列挙fixtureで確認し、phase境界やpassを明示する。有限の可到達集合の上限と、実際に生成した集合の数を混同しない。

2026-11-17の人間指示: 局数を16から増やせば、5–6手目以降にも不足や重複が起こり得る。1–4等の固定境界や16局を特別扱いせず、operatorが選んだ規模と各phase・splitの実際の重複排除後のcoverageに基づいて処理する。局面生成の試行上限と利用可能数を記録し、上限到達やsplit不足を明示する。0固定の例外を除き、同じ判定を対象の全phaseに適用する。

追加の人間指示: 指定された局面数を用意する際、既出canonical局面なら再生成し、同じphase・splitで新しい局面を得ずに連続10回重複したらそのphase・splitの生成を打ち切る。新しい局面を採用したとき連続重複回数を0に戻す。上限はoperatorが変更でき、実際の値をmanifestに固定する。要求数に満たなくても有効な局面で学習を続け、要求数・獲得数・重複回数・試行数・打ち切り理由・split欠測を出力に残す。これは重複が続いたための打ち切りであり、全合法局面を列挙し尽くした証明ではない。trainが0で固定値規則にも該当しないphaseは学習済みとせず明示的に停止する。生成試行全体にもoperator指定の有限上限を設け、再開時に同じ計画・保存済みunitから続ける。

人間の指示に基づき phase 0 は全重み0の表により評価値0を保証し、固定値という来歴を記録する。phase 1–9 は合法で多様な自前局面を決定的に生成し、保存した局面と分割を固定する。重複canonical局面を異なるsplitに入れず、分割不能なphaseはvalidation/test unavailableと記録し、欠測を0や合格扱いしない。局面数とsplitの実測、seed、資源制限を記録する。局面ごとの値は自前生成データ由来とし、外部エンジンを教師データ源にしない。

局面を個別に初期配置から作るか既存poolを再利用するかは、保存済み局面の互換性、生成の有界性と検証可能性を満たす方法を実装時に選ぶ。単なる局数増加やseed変更では phase 0 のsplit不能は解決しない。元runのcompleted gamesを利用できる場合は読取専用で互換性を検証し、新producer commitを固定した新rootに出典を残す。利用できない場合も根拠を報告し、原本を変更しない。

現行 `table32_import.py:34-47,107-109` はsplit間の重複を含む元局を拒否するため、既存の `--import-games-from` による直接再利用はできない。再利用するなら専用の明示的な入力policyで出典と全exposureを記録し、新split契約の下で衝突を排除・割当て直して検証する。局を黙って改変したり旧runを遡って成功にしない。

## 既存参照

- `docs/specs/reversi-ai.md` の project-owned table32 pilot / 部分学習 / 結合契約。
- `docs/exec-plan/todo/0054-reversi-ai-next-method-experiments.md` — 実験全体と人間実行境界。
- `tools/reversi-ai-training/table32.py:141-149,513-595` — partial設定、pool省略、generationと抽出。
- `tools/reversi-ai-training/table32_inputs.py:49-110,220-296` — phase、合法prefix、early poolとlabel。
- `tools/reversi-ai-training/table32_extract.py:57-126` — canonical重複、splitとcoverage。
- `tools/reversi-ai-training/table32_optimizer.py:79-110` — 空validationを区別するoptimizer。
- `tools/reversi-ai-training/table32_combine.py:20-165` — receiptとphase来歴の結合。
- `tools/reversi-ai-training/README.md` — 運用手順とresume契約。
- checkout外 `.local/reversi-ai-runs/0054-20261114-phase0-9/` のmanifest、reportと完成局、 `0055-20261117-combined-10-59/` と5 source roots。過去の出力は実行時に存在・digestを再確認する。

## 変更マップと手順

1. (MODIFY) `docs/specs/reversi-ai.md` に先に黒箱契約を追加。phase 0固定値の意味と表現、phase 1–9の局面生成とsplit、欠測報告、保存済み局の互換条件、新root・再開・結合・独立検証を規定。既存full cycleと他phaseの契約は維持。
2. (MODIFY) `table32_inputs.py` / `table32.py` / `table32_extract.py` と必要な `table32_optimizer.py`, `table32_verify.py`, `table32_model.py`, `table32_combine.py`。有限の合法局面の重複排除、split可能数を凍結し、0固定表を明示的な来歴とともにexport。固定表が他の任意のphaseの欠落を隠さないようにする。receipt・offline replay・結合時に区別できるようにし、既存artifactの読取互換と重複phase拒否を保つ。
3. (MODIFY) 関連testに、phase 0–4のcanonical数、0の評価、局面不足・split欠測、cross-split漏洩拒否、生成の再現性、interrupt/resume、改ざん検出、過去runの保持、0–9と既存形の10–59との結合をfixtureで追加。trainer・CLI・Oracleを起動しないoffline検証も確認。実際の保存済み原本をfixtureとみなさない。
4. (MODIFY) `tools/reversi-ai-training/README.md` に新root・operator controls・完了/欠測の確認と停止時の回復、0–9を既存の5 source rootsと結合するコマンドを記載。結合済みrootを入力sourceとして誤使用しない。新candidateによる独立評価は別の人間操作。
5. (DELETE) 完了した本計画。0054は実験の独立検証・結論まで残す。

## 検証

仕様を先に更新してから実装する。関連Python fixture、Rust側に変更がある場合のAI tests、lintおよびworkflow lintを実行し、通常のPR reviewに進む。実在rootはread-onlyのidentity/互換確認のみで、実学習、実対局、Oracleは開始しない。検証できない生産入力の前提や、有限局面の検証不足をPRに明記する。
