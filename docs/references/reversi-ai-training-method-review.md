# 学習方法の一次資料調査と0037の選択

## 2026-10-25の採用状態と0052比較

0037の同方式pilotに続き、0019の64局cycleは完走・独立検証を終え、
candidateを現在のTrainedEvaluatorモデルとして採用した
（[identityと実成績](reversi-ai-0019-adopted-model.md)）。
Oracle診断は0勝20敗で、別方式の実行可能な後続計画はこの時点で存在しなかった。
既存の0008はStrategicEvaluator向け、0037は同じ更新方式のpipeline検証である。

ユーザーの選択に基づき、整数一回更新とf64 Adamの反復更新を、同じ初期baseline・
同じ0019教師行で比較した。結果は[0052実比較記録](reversi-ai-optimizer-comparison.md)
に記録する。validation MSEの厳密改善条件を満たさず`not-improved`となり、比較対局は
開始されなかった。採用済み0019モデルはそのままで、0018受け入れ結果も主張しない。

2026-10-25に[公式技術解説](https://www.egaroucid.nyanyan.dev/ja/technology/explanation/)と
[v7.8.1のoptimizer](https://github.com/Nyanyan/Egaroucid/blob/v7.8.1/src/tools/evaluation/eval_optimizer_cuda.cu)を再確認した。
参考にできるのは反復最適化、validationによる停止、局面分布の多様化などの方法である。
教師データはproject-owned生成に固定し、Egaroucid/Edaxの対局・公開棋譜・評価値・重みは教師にしない。
既存Oracle corpus/goldenは診断・正しさの検証に限る。
自己対局の複数cycleや多様なopening、phase別件数の改善は、更新方式の実結果の後に別計画で扱う。

## 0037で採用した方法の調査記録

2026-10-14に公開資料と下記固定sourceを確認した。学習方法の参考であり、
上流の重み・データ・runtimeを製品やGDExtensionへ取り込むものではない。
Egaroucid/Edaxは引き続きMake/scripts/CI側の外部ツールとする。

## Egaroucid

固定sourceは `e4bd1db9d6d56052c27d9aaed58e9366d00b226c`。
[技術解説の日本語原文](https://www.egaroucid.nyanyan.dev/ja/technology/explanation/)と
[英語版](https://www.egaroucid.nyanyan.dev/en/technology/explanation/)は可変資料であり、
固定sourceの実装と区別する。英語版には機械翻訳の注記がある。

| 対象 | 確認できた内容 | 一次資料 |
| --- | --- | --- |
| 対局生成の説明 | ランダム序盤の後、旧版Level11同士で対局し、ランダム区間を学習から除く。以後の局面には終局値を与える | 技術解説のTraining Data |
| 序盤の説明 | 初手から11手までのunique openingを列挙し、7.4.0 Level17の評価値を使う | 同上 |
| 特徴定義 | 有効includeは7.5定義。16基本パターン・64配置と手番側石数、60フェーズ、内部スケール32 | [definition](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/tools/evaluation/evaluation_definition.hpp#L17)、[7.5定義](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/tools/evaluation/evaluation_definition_20241125_1_7_5.hpp#L34) |
| 色と教師値 | player/opponent/emptyの三進表現。transcript展開時には終局値を各局面の手番色に合わせて符号反転 | [board](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/engine/board.hpp#L266)、[展開処理](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/tools/convert_board_data/expand_transcript.cpp#L63) |
| 終局値の意味 | 勝者に空きを加算する。占有石数の単純差とは異なる | [score_player](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/engine/board.hpp#L378) |
| 対称性・更新 | 同じパターンの配置で表を共有し、元indexと鏡像indexへ残差を加算。CUDAのAdamを使う | [特徴定義](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/tools/evaluation/evaluation_definition_20241125_1_7_5.hpp#L203)、[残差](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/tools/evaluation/eval_optimizer_cuda.cu#L178)、[Adam](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/tools/evaluation/eval_optimizer_cuda.cu#L387) |
| split | 各phaseの行をshuffleし、phase>11で5%をvalidationに使う。phase<=11は共有 | [optimizer](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/tools/evaluation/eval_optimizer_cuda.cu#L496) |

固定optimizerのshuffle対象は特徴indexとscoreだけを持つ構造体である
（[Adj_Data](https://github.com/Nyanyan/Egaroucid/blob/e4bd1db9d6d56052c27d9aaed58e9366d00b226c/src/tools/evaluation/eval_optimizer_cuda.cu#L60)）。
対局/opening/対称群による独立splitはこのsourceからは確認できない。
技術解説の検証用対局はランダム序盤N=0..12後のLevel30で、序盤の集合は共有と説明されている。
固定sourceを一括して「7.7の学習実装」と呼ばず、説明と7.5実装の差を保持する。

## Edax

固定sourceは `14f048c05ddfa385b6bf954a9c2905bbe677e9d3`。
[eval.cのパターン配置](https://github.com/abulmo/edax-reversi/blob/14f048c05ddfa385b6bf954a9c2905bbe677e9d3/src/eval.c#L36)では
角・辺・内側の直線・対角線を確認した。
[係数表](https://github.com/abulmo/edax-reversi/blob/14f048c05ddfa385b6bf954a9c2905bbe677e9d3/src/eval.c#L460)は
手番切替用2表、61 ply、47特徴。
[index展開](https://github.com/abulmo/edax-reversi/blob/14f048c05ddfa385b6bf954a9c2905bbe677e9d3/src/eval.c#L485)は
三進の0/1交換による相手視点と幾何対称のpacked indexを使う。
[読み込み](https://github.com/abulmo/edax-reversi/blob/14f048c05ddfa385b6bf954a9c2905bbe677e9d3/src/eval.c#L555)は外部評価ファイルから
ply別係数を展開し、[盤面評価](https://github.com/abulmo/edax-reversi/blob/14f048c05ddfa385b6bf954a9c2905bbe677e9d3/src/eval.c#L747)は
空き数からplyを計算する。終局の勝者空き加算は[0046調査](reversi-ai-exact-score-contract.md)に記録済み。

学習対局の生成、教師値生成、optimizer、train/test splitは、この固定srcの
評価runtimeから確認できない。Egaroucidの工程をEdaxの工程として補完しない。

## 今回固定する方法

ランダムな合法opening収集と教師値生成を分ける。黒先手の標準盤面から
6個の独立openingを再生し、baselineのproject AIで終局まで継続する。
教師値はこの対局のterminal winner-empty値を手番側へ符号変換したもの。
random rollout終局値も、各局面のminimax exact値も、この教師値ではない。
残り30空きから毎手完全読みする方式は選ばず、追加の高閾値性能評価をpilotの必須工程にしない。

自己対局は8/8/8・exact16・turn、比較とcorpus判断は12/12/12・exact16・turn。
[0040結果](reversi-ai-efficiency8-closeout-2026-10-13.md)はStrategicEvaluatorの探索器/ハーネスの
実行可能性を示す。TrainedEvaluatorの速度や学習成功は別途記録する。
time/node capとprotocol timeoutはprepareで固定し、失敗対局から教師値を採らない。

既存のproject-owned 64特徴・60phaseと一回の`bounded_td_v1`を維持する。
整数残差を64で割って丸めるため小さい残差では重みが変わらない場合がある。
成功を仮定せず、artifactと不成立の独立指標を保存する。
Oracleの固定値はcorpus regret比較だけに使い、教師へ混ぜない。

baselineのtrain原本、validation、held-out、corpus、0018予約openingをdigestで固定し、
D4同値の重複とsplit間混入を排除する。比較は未使用の合法opening10個を
同じ盤面で2回再生し、candidate/baselineの座席だけを交換する。
改善判定はheld-out MSEの低下、validation MSEと平均regretの悪化10%以内、
20局で10 match points以上を事前固定する。ゼロ基準はゼロを維持する。
独立指標の改善が成立しても、このpilotの観測に限定する。

2026-10-14時点で新契約の本番入力は未生成とユーザーが確認した。
ツール検証と実pilotの完成証拠を分け、0037計画と0019 freezeを残す。
