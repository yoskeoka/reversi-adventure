# 現在採用するTrainedEvaluatorモデル

`0019-20261020-02.json`は、人間操作の0019 runで選択され、2026-10-25に
全phase・原本・ゲーム・更新artifact・指標を独立再検証したproject-ownedモデルである。
ユーザーの採用判断により、PlaygroundのTrained対局者とTrained Advisorの既定モデルとする。
元artifactをbyte単位で同梱しているため、元の学習用checkoutや`.local`への依存はない。
上流エンジンの重み・教師データは含まない。

| identity | 値 |
| --- | --- |
| file SHA-256 | `13e8bdf59553746ba32ce47b53a09c011eb79223cabf4ddefb224b2640d283de` |
| internal artifact digest | `ec45162b1020dac3c709b0469ac5a12d5149cce44c5c537ed837dc7bc0c74fca` |
| weight digest | `1c8ffd775feabbc663e4e6f9aef7972738bc5719342f834671fdd99e3827d009` |
| bytes | 2,748,742 |
| format / score | format2 / `winner-empty-v1` |
| provenance license | `CC0-1.0` |
| original run | `0019-20261020-02` |
| original relative path | `phases/candidate-update/attempt-0001/candidate-artifact.json` |
| original producer commit | `7c2fe9a4f62517e8efb28856424e1be2bf9d890d` |
| retry / independent verification commit | `46489881f2bf0c6eb014f3d12e1abeca76ba564b` |
| completed report canonical digest | `bc111322c908ad350eb716f688002ec9eab4c530d3b6f29a3ae71d01617ea3ce` |
| completed report file SHA-256 | `5954f980d7e019b3b73fc2c379f6de18f619935b476210401a31dffa86b0bbdb` |

自己対戦64局・教師3,364行を使い、旧baselineとの200局で190勝8敗2分、191 match pointsを得た。
validation 13,401局面のMSEは333.2821431236475から321.5026490560406、
12 corpus局面の平均regretは1.8333333333333333から1.1666666666666667になった。
Oracle診断は0勝20敗0分。候補は12/12/12・exact16・turn・bookなし、
OracleはEgaroucid 7.8.1の`oracle-0018-acceptance-v1`（6/6/6・exact12・bookなし）。
この採用は0018の勝率50%以上の受け入れを意味しない。

Playgroundのinstall/startはfile SHA-256を検証し、checkout外cacheへコピーする。
既存demo設定もstart時に更新する。`PLAYGROUND_CONFIG`で明示指定したモデルは優先される。
モデルを更新する際は、assetとsetupのpinを同じPRで変更し、runtime probeを再検証する。

CLIから直接使う場合は、このassetを`--evaluator trained --trained-artifact models/trained/0019-20261020-02.json`で指定できる。
TrainedEvaluator自体やGodotの既定評価器を変更するPRではない。
