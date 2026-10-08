# 探索設定・速度・強さの現在地

2026-10-08の判断材料。merged [PR #255](https://github.com/yoskeoka/reversi-adventure/pull/255)
と0046実装元 main `2b56e8f`、保存証拠を参照する。新しい対局・学習・Oracle solveは起動していない。

全体目標は計算資源ハンデ付きOracleへの勝率50%。現在は強化学習の足かせを減らすため、
探索エンジンの性能改善とscoreバグの調査/修正を進める段階である。
性能改善の開始前に強化成功や最終勝率を要求しない。
エンジンの正確性と速度→小規模学習pilot→本番強化→最終勝率受け入れの順に進める。

## 何が選べるか

| 経路 | 現在 | 今回の方針 |
| --- | --- | --- |
| 通常CLI | 3phase深度とexactを明示指定可能、既定exact16 | 既定・受理範囲を維持 |
| Playground/Advisor/decision | opening1..12、midgame1..16、exact0..30。24は既に選べる | 柔軟な選択を維持 |
| Godot | 旧 `set_ai` 互換、新 `set_ai_with_exact_threshold` | 深度各1..64、exact0..30、変換前に検証 |
| 自己対局manifest | schema5で自己対局の3phase/exactを独立指定 | 深度各1..64、exact0..30、既定12/12/12・exact16 |
| 候補比較/0018 | 固定strong-v1、12/12/12・exact16 | 校正条件を維持 |

ユーザーは既定20への変更を求めていない。必要なときに必要な読みの深さを指定できることが目的。
設定可能であること、時間内に完了すること、正確性・強さの受け入れは別の条件。
0046のscore調査・残条件は[score契約記録](reversi-ai-exact-score-contract.md)を参照する。
schema3/4の完成reportは元契約でoffline検証できるが、新規runへ読み替えない。

## 速度と正確性

| 証拠 | 結果 | 判断できる範囲 |
| --- | --- | --- |
| 修正後0045、12/8/12・exact20、各3局 | turn平均519.254秒（8分39秒）、game502.221秒（8分22秒） | 固定3開局の観測時間 |
| 同じ0045のexact部分 | 平均51.907秒 / 50.835秒 | 全局の約10%。heuristic時間差をcache効果にしない |
| 同じ0045の正確性 | 全3組が意味一致、抽出6 root/10 query一致 | 選択位置のみ。opening-4は早期終局で抽出0 |
| 旧0041のexact24 pilot | 8 window中4完成、4時間切れ | 一部黒rootは約309秒に達した。新実装の所要時間保証ではない |
| 空き16系列のscore | CLI ±39 / Oracle ±40 | 0046の4独立solveでscore契約差をterminal/root/childまで確認 |

0045のwall差3.28%は反復なし、heuristic nodesも同一であり、有意なcache高速化とは判断しない。
0046の終局は白51/黒12/空き1で、projectは実石数差39、Oracle/Edaxは勝者への空き加算で40。
ユーザーの指定によりOracle/Edax規則へ揃える方向を採用し、別の修正計画で移行する。
production式・既存教師値の意味はまだ変更していない。本番freezeのgateは残る。
2–3分/局の目安は未達。学習を回せる速度にするための追加改善と時間予算を0040で整理する。
12/8/12・exact20の今回のturn平均を単純に掛けると、6局は約52分、64局は約9時間14分。
これは同じ3開局の時間による概算で、本番runの予測保証ではなく、学習更新・候補比較・regret時間も含まない。
旧8局と今回3局はbinary/棋譜が異なるため、直接の改善率にしない。
詳細は[0041記録](reversi-ai-exact-threshold-reuse-assessment.md)とPR #255の正確性記録を参照する。

## 強さ・学習成績

| 段階 | 検証済みの状態 | まだ判断できないこと |
| --- | --- | --- |
| 0032 baseline | held-out 13,407行、MSE 314.4795、zero-weight 316.7607 | 約0.72%の予測誤差改善は対局勝率ではない |
| 0019 reinforcement | 旧v1失敗、旧v2停止。現存directoryはmanifest/CLIのみ | 完成した本番候補・強化成功の成績は未確認 |
| 0037 pilot | 6自己対局/768教師行/20比較局の計画 | pilotの更新前後の独立改善は未測定 |
| 0018最終受け入れ | restricted Oracleへのwins/all games ≥50%を目標とする計画 | 現在の勝率、目標達成、confidence条件は未評価 |

速い設定ほど強い/弱いという比較結果はない。今回の6局は速度/正確性診断であり対外勝率試験ではない。
現在の候補の強さを判断するには、0037の独立pilot、0019の候補検証、0018のheld-out受け入れが必要。
この未評価は現在のエンジン性能改善を止める理由ではなく、改善後に測る下流の成績である。
出典は[0032の完了記録](reversi-ai-random-inputs-0032.md)、0019/0037/0018の現行計画。

## 0032は完了済み

[PR #223](https://github.com/yoskeoka/reversi-adventure/pull/223)は全2,560局の生成/再生検証とbaseline検証を完了し、
0032計画を削除した（commit `30ea3bd`）。新しく0032を実行する依存ではない。
保存manifestのproducer `790209d9c69fc109141a9d5190e694b52edd1794`のGit blobから
random_inputs.py/reinforcement.py/training.pyのSHA-256を再計算し、3つとも保存pinと一致した。
現行sourceは変更されているため一致しない。これは凍結producerの破損を意味しない。

今回は全量replayを再実行していない。0019の新freeze前に、記録producer・元契約で
入力digest/全game/provenanceを再検証する。凍結producerでも失敗する場合だけ具体的な失敗を別計画へ切り出す。
benchmark用artifactの検証と、学習元game全体の再検証は区別する。
