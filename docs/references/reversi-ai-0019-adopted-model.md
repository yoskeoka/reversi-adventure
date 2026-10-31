# 0019完了記録と現在採用するTrainedEvaluatorモデル

2026-10-25、人間操作run `0019-20261020-02`の完成出力を独立に再検証した。
ユーザーはこの候補を現在のTrainedEvaluatorモデルとして採用し、次は同じ教師データで
更新方式を比較すると判断した。0019の一回のcandidate cycleは完了とする。
後続も教師データを自前で生成し、Egaroucidの棋譜・評価値・重みを教師へ取り込まない。
0019計画は既に実装PRの履歴へ移されており、目標未達を理由に再開しない。
更新方式比較は[0052の実比較記録](reversi-ai-optimizer-comparison.md)に記録した。
projected Adam候補は改善せず、この0019 artifactを現在の採用モデルとして維持する。
最終勝率の受け入れは[0018](../exec-plan/todo/0018-reversi-ai-strong-engine-acceptance.md)が担う。

## 採用identity

run-rootはcheckout外の
`/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-runs/0019-20261020-02`。
以下の相対pathはこのrootを基準とする。原本は移動・上書きしない。

| identity | 値 |
| --- | --- |
| report | `report.json`、schema2、`run_status=complete` |
| report canonical digest（実行時の表示値） | `bc111322c908ad350eb716f688002ec9eab4c530d3b6f29a3ae71d01617ea3ce` |
| report file SHA-256（末尾改行を含む） | `5954f980d7e019b3b73fc2c379f6de18f619935b476210401a31dffa86b0bbdb` |
| manifest file SHA-256 | `efc0c268435d6f16944449696ac34f1943e06e0d1e6e13be4ed2de8592412e40` |
| selected / candidate-update artifact | `phases/candidate-update/attempt-0001/candidate-artifact.json` |
| artifact file SHA-256 | `13e8bdf59553746ba32ce47b53a09c011eb79223cabf4ddefb224b2640d283de` |
| artifact internal digest | `ec45162b1020dac3c709b0469ac5a12d5149cce44c5c537ed837dc7bc0c74fca` |
| weight digest | `1c8ffd775feabbc663e4e6f9aef7972738bc5719342f834671fdd99e3827d009` |
| score / artifact format | `winner-empty-v1` / format2 |
| original execution commit | `7c2fe9a4f62517e8efb28856424e1be2bf9d890d` |
| Oracle retry / verification commit | `46489881f2bf0c6eb014f3d12e1abeca76ba564b` |

reportの`execution_commit`は元のproducerを表す。各phaseと各Oracle gameの実行commit・設定は
`phase_provenance` / `oracle_game_provenance`を参照し、一つのcommitへ読み替えない。
Oracle attempt-0001の失敗証拠を保持し、timeout310秒で完了済みの7局を引き継いだ。
attempt-0002ではtimeout1800秒で残り13局を完了した。

## 観測値と採用判断

| 指標 | 結果 |
| --- | --- |
| 自己対戦 / teacher rows | 64局 / 3,364行 |
| raw candidate vs pinned baseline | 190勝8敗2分、191/200 match points |
| validation MSE（13,401局面） | baseline 333.2821431236475 → candidate 321.5026490560406 |
| corpus平均regret（12局面、除外0） | baseline 1.8333333333333333 → candidate 1.1666666666666667 |
| raw candidate vs Egaroucid | 0勝20敗0分、0/20 match points |

候補比較は同一openingを座席交換した200局。`match_points > games/2`を満たしてcandidateを選択した。
Oracleは`oracle-0018-acceptance-v1`、bookなし・1 thread、Egaroucid 7.8.1の深度6/6/6・exact12。
candidateは深度12/12/12・exact16・turn、bookなし、300000ms / 10000000 nodes。
この診断20局は0018の独立held-out受け入れではなく、勝率50%以上を達成した証拠ではない。
改善の原因を特定した結果でもない。

## 独立検証

検証codeは上記`46489881...`。`production_cycle.load_context`で0051 bundle・baselineを
入力原本から再構成し、全8phaseの`latest_success` / `verify_receipt`で出力digestを照合した。
`check_dependencies`、`verify_failed_attempts`と全phaseの`semantic_phase_check`を通した。
これには全保存ゲームの合法replay、teacher rowsと更新artifact、候補選択、validation MSE、
corpus regret、Oracle gameの再開元・集計、最終reportの再構成を含む。
rootのreportとoffline-verification出力の一致、提示canonical digest、採用artifact file SHA-256も一致した。
追加の学習・対戦・Oracle solveは実行していない。

## 利用方法

TrainedEvaluatorを使う際は上記artifactを明示指定する。ファイル名の`candidate`は変更せず、
この採用記録で現行モデルのidentityを固定する。

```sh
rtk ./target/release/reversi-ai-cli --evaluator trained \
  --trained-artifact /home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-runs/0019-20261020-02/phases/candidate-update/attempt-0001/candidate-artifact.json \
  --opening-depth 12 --midgame-depth 12 --endgame-depth 12 \
  --exact-solver-empty-squares 16 --exact-cache-scope turn \
  --time-limit-ms 300000 --node-limit 10000000
```

Playgroundの外部JSON設定では`trained.artifact`に同じ絶対pathを指定する。
CLIのartifact明示指定契約、他の評価器、Godotの接続方法は変えない。
次の学習比較では今回の採用モデルを比較相手としてpinし、結果を見て自動的に置き換えない。
