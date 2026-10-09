# Winner-empty score の移行境界

0047 は AI 終局と新規教師値に `winner-empty-v1` を採用する。
両者合法手なしの盤面で手番側の実石数差を `d`、空きを `e` とすると
`d + sign(d) * e`。引き分けと空盤は0、片色のみは±64、満盤は従来通り。
固定 Edax/Egaroucid の調査根拠は
[0046記録](reversi-ai-exact-score-contract.md)と保存 fixture に残す。
新しい Oracle solve、全局計測、本番学習は今回起動しない。

## 新旧 identity

新規探索は semantics2 / Advisor v2。新規学習は trainer v2、record/manifest2、
artifact/feature format2、scale `winner_empty_v1`、target
`winner_empty_v1_for_side`、trained runtime2を使用する。
reinforcement は producer v4 / manifest6 / game・report・checkpoint4、
random inputs は producer/source v2 / schema2。
Oracle は golden/analysis2、whole-game は producer v3 / manifest2 / report3 /
evidence2、threshold/cache は v2。新形式は明示score contractを固定する。

旧 artifact、学習原本、golden/reference、receipt と失敗/未完了状態は保持する。
旧 Python 証拠の検証は `--legacy-offline` のみで行い、凍結 producer と旧式を使う。
CLI/Godot の新 runtime は format1 artifact を拒否する。
旧 raw差教師値を solver の wipeout ±64へ読み替えない。
random v1 は保存された source snapshot/commit で検証し、現行 source digest に置換しない。
0032のように組込みsnapshotより古い入力は、`random_inputs.py verify --legacy-offline`
に `--legacy-source-dir /original-checkout/tools/reversi-ai-training` を指定する。
原manifestに固定された3 sourceのSHAを検査してから隔離importし、原checkoutのGit ancestryも検証する。
benchmark旧証拠は元Git revisionからvalidatorを読み出すため、その履歴を必要とする。
履歴欠落は明示失敗とし、CIのOracle harness checkoutは全履歴を取得する。
新 root/child minimax 値を旧値へ一律補正したり終局情報だけで移植したりしない。

物理 `Game::score` / Godot・UI 表示 / `disc_counts` / random `black`・`white` /
whole-game `score_black` は実石数。教師値と AI score の意味変更は最善手・PVにも影響しうる。
feature/catalog・境界・設定範囲・preset・既定 exact16・turn policy は維持する。

## 検証と残る本番 gate

小さい独立 fixture で終局、満盤、draw、wipeout、空盤、pass、root/選択child/PV leafを検証する。
cache bound/衝突/中断/context/reset、旧artifact拒否、schema/producer/contract/digest改変拒否、
旧完成証拠の元意味での offline 検証を対象とする。検証コマンドと結果は実装 PR に残す。

2026-10-10のローカル検証はengine/AI 149件、profiler identity 5件、training 44件、
Oracle 46件、benchmark core 143件、comparator/diagnose 6件、Playground Node29件/Python2件が成功した。
最終migration/whole-game fixture再確認は39件成功。Godot build、必須workspace Clippy、fmt、
Playground lint/buildも成功した。旧goldenと16 referenceの明示offline検証が成功し、
旧golden/reference/学習fixture/保存receiptに差分はない。旧minimaxの再solveはしていない。

production freeze は解除しない。0040 の最新 producer による独立 root/child 一致、
資源制限応答、人間の設定/性能判断、0037 pilot、0019 の新契約 baseline/validation と候補 cycle、
0018 の held-out handicap 受け入れを別々に完了する必要がある。
`strong-engine-hcap-v1` は12/12/12・exact16。本番入力再生成・再学習は人間操作の別計画で
件数/上限/進捗/再開と原本 digest を固定し、別directoryへ出力する。

起動時の `ww` stale-main 再発は既存
[issue 0015](../issues/0015-ww-create-stale-main.md)へ記録した。
実装は0046 #257と計画 #258を含むmerged main `d6a8589`から開始した。
