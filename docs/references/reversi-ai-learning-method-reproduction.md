# 成功例の学習工程を基準にした次候補の検討

## 検討境界

2026-11-01、0052/0053のnegative closeout後の次候補を検討した。
当初の丸め・開始artifact・cycle・opening・phase・exact閾値という6分割は、
現行pipelineの局所変更に寄りすぎていた。人間の意図は、先に成功例の方法を
工程全体として再現し、その比較結果から必要な要因分析へ進むことである。
そのため旧6案を確定候補とせず、公開方法の再現を基準に計画を組み直す。
この検討では学習・対局・Oracle診断を実行していない。

0052/0053は自前3,364教師・既存feature/runtime boundの下でのprojected Adam比較であり、
Egaroucidの学習工程の再現実験ではない。
[実比較記録](reversi-ai-optimizer-comparison.md)の7.0/20点を、
Egaroucid式学習全体の否定や0018の受け入れ結果へ拡張しない。

## 公開一次資料と対象revision

- [Egaroucid公式技術解説](https://www.egaroucid.nyanyan.dev/ja/technology/explanation/)：
  学習データ、最適化、深層学習の節を2026-11-01に確認した。可変文書である。
- source revision `67aa89f18bfd22fa35730cdc0a9f4e7501c2239a`：
  [active definition](https://github.com/Nyanyan/Egaroucid/blob/67aa89f18bfd22fa35730cdc0a9f4e7501c2239a/src/tools/evaluation/evaluation_definition.hpp)、
  [model / scale](https://github.com/Nyanyan/Egaroucid/blob/67aa89f18bfd22fa35730cdc0a9f4e7501c2239a/src/tools/evaluation/evaluation_definition_20241125_1_7_5.hpp#L34-L70)、
  [feature sharing](https://github.com/Nyanyan/Egaroucid/blob/67aa89f18bfd22fa35730cdc0a9f4e7501c2239a/src/tools/evaluation/evaluation_definition_20241125_1_7_5.hpp#L198-L242)、
  [Adam](https://github.com/Nyanyan/Egaroucid/blob/67aa89f18bfd22fa35730cdc0a9f4e7501c2239a/src/tools/evaluation/eval_optimizer_cuda.cu#L385-L414)、
  [step/export](https://github.com/Nyanyan/Egaroucid/blob/67aa89f18bfd22fa35730cdc0a9f4e7501c2239a/src/tools/evaluation/eval_optimizer_cuda.cu#L580-L745)。
  active includeは7.5用definitionを指す。説明の7.7モデルや7.8.1配布weightと同じ
  学習runを再現できることまでは確認していない。
- [既存の調査](reversi-ai-training-method-review.md)は過去revisionの記録として保持し、
  source versionと当時の選択を今回の再現仕様へ黙って読み替えない。

## 工程の比較

| 工程 | 公開方式で確認した内容 | 現在の0052までの方式・再現上の課題 |
| --- | --- | --- |
| 中盤以降の教師 | 様々な長さのランダムprefix後に過去版AIで対局し、prefixを除いて終局値を付ける | 0019は固定8/8/8・exact16、64局。ランダムprefixの多様な長さと配分を再現していない |
| 継続の探索 | 説明ではLevel11（中盤11、終盤25読み切り） | 自前エンジンの同等設定の実行可能性は未確認。外部AIを教師にする代替は採らない |
| 序盤 | 11手までのunique局面を列挙し、別の探索でラベル付け | 現行のrandom input終局値と異なる。列挙範囲と自前探索の上限を明示する必要がある |
| モデル | 固定sourceは16pattern tableを64配置で共有し、手番側石数featureを追加。60phase | 現行8base×8変換の64feature・盤面canonical化と同一ではない |
| 数値表現 | scale32、raw parameter上限4091、int16 table | 現行はweight[-1,1]、合計[-64,64]。小数情報と表現範囲が大きく異なる |
| 最適化 | phase全体を使うdouble Adam、出現回数でparameter別learning rateを調整 | 0052はbatch256のprojected Adam。Adamという名前だけでは同じ方式にならない |
| export | ceil/floor候補とtraining lossによる整数化調整、反転indexを共有 | 0052はhalf-away-from-zero。export手順の再現が必要 |
| runtime score | raw32を特徴総和後にhalf-away-from-zeroで÷32し、石差範囲へclip | 探索とterminal/exact scoreを32倍する方式ではない |
| 分割 | 説明では序盤の列挙データを共有する例がある | 本プロジェクトでは独立評価・0018 held-outを優先し、この共有は再現しない |

公式説明の中盤以降の教師は終局値であり、全てのランダム盤面に30空きからの
minimax正解値を個別付与する手順ではない。
現行0037/0019の採用記録も、自前継続対局のterminal winner-empty値を教師としている。
30空き完全読みは過去に候補として検討したが、採用実行済みとみなさない。

公開資料内でも大規模データのAdam表学習と、小型pattern networkで学習して
表へ展開する方法を区別している。後者は同作者が少ないデータ向けの利点を述べている
別方式であり、前者の一部として無断で混ぜない。

固定sourceのAdamはbeta=.9/.999、epsilon=1e-7、parameter別LRは
`alpha/min(50,appearance_count)`。出現0は更新しない。
prediction clip・parameter limitが有効、warmupは無効である。
validationが同値以上の改善ならpatienceをresetし、悪化連続回数が100を超えたら停止、
10回でLRへ0.7を掛けるwrapper設定がある。停止時weightをexportし、
best weight復元を行う実装ではない。alphaそのものはwrapper引数であり、
上流の確定学習run値が判明したとは扱わない。
整数化探索は上流ではwall60秒で制限され、seedはrandom_device由来。
再現性のためのseed固定・回数上限は本プロジェクトで追加する差分となる。

runtimeは[generic evaluatorの515–525行](https://github.com/Nyanyan/Egaroucid/blob/67aa89f18bfd22fa35730cdc0a9f4e7501c2239a/src/engine/evaluate_generic.hpp#L515-L525)
で確認した。各tableを先に丸めず、総和に対して正負付き16を足して32で0方向除算し、
石差へclipする。raw ±15→0、±16→±1を含めて再現し、既存searchの石差単位と混ぜない。

## 再現の呼び方と禁止事項

公開方法を再現するとは、データ生成・教師値・feature共有・数値精度・optimizer・
exportを一組の方法として定義することである。複数要素が変わる比較は方式全体の比較とし、
どの一要因が効いたかは結論にしない。
CPU実装やデータ量縮小などの差は一覧に残す。小規模試験の不成立は、
上流規模や上流モデルの性能を否定したことにならない。

- Egaroucid/Edaxの棋譜・評価値・重み・公開学習データを教師へ取り込まない。
  参照するのは公開された方法で、生成・ラベル付けはproject-owned sourceで行う。
- 原本0051/0019/0052/0053と採用0019 artifactを保持する。新表現は新artifact identityと
  evaluator contextを持つ別候補とし、既存TrainedEvaluatorへ暗黙に読み替えない。
- 0018 suiteは候補選定後にfreezeする。今回の方法・データ量・重み・停止設定の選択に
  その局面や結果を使わない。
- optimizer flags、alpha schedule、反転共有、prediction clip、export、初期値、
  実験のseed・停止条件を固定する。公開説明・最新版source・旧wrapper設定を混ぜない。
- 本番学習・対戦・Oracle診断は人間が別途開始する。計画作成中に実行しない。

## 今回の選択

人間は表＋Adam方式1本に絞り、128局（train96/validation16/test16）＋序盤最大256局面で
学習サイクルを回せるか先に確認することを選んだ。
pattern networkやEdax等の別方式へ今回の調査を広げない。
具体的な実行可能性gate、prefix配分、学習step/export上限、独立評価、
失敗と再開は[0054](../exec-plan/todo/0054-reversi-ai-next-method-experiments.md)に定義する。
これは計画の選択であり、実行開始の指示ではない。

4,000局等を十分な学習量とする根拠はない。局数と教師局面数を分け、
phase・pattern coverage、teacherの質、学習曲線、資源を見て拡大規模を相談する。
今回の小規模完走だけで最終必要量を確定せず、拡大は別計画にする。

## 0054 toolingの実装と残る実比較

新候補を `reversi-ai-pattern-table32-v1` と明示CLI `trained-table32` に隔離した。
[catalog](../specs/reversi-ai-table32-catalog.md)に16表・64配置・反転置換を列挙し、
共有JSONのcanonical SHA-256は
`c6ffc6bf14dab5712bbb053d4a7222b9155d260c7ce706c998ea095d98d81616` とした。
65feature、raw32総和後の符号付き丸め、int16 parameter範囲、60phase、artifact provenanceと
digestをPython/Rustで照合する。既存0019 artifactの意味と既定モデルは変えない。

CPUの安定した走査順、固定seed、phase独立のfull-batch Adam、step上限、
整数exportの提案回数上限と60秒sliceの中断再開は、決定性と有界実行のための意図した差分である。
上流CUDA、wall60秒で完了させる非決定的export、配布weight、上流規模や強さの再現とは区別する。
今回の既定規模は自前128局＋序盤最大256rootであり、十分な学習量という主張ではない。
実装中の[追加指示](../specs/reversi-ai.md#2026-11-01-追加の人間指示-開始scriptとパラメータによる拡大)により、
toolingは同じ開始scriptの明示パラメータだけで、初回既定値を超える規模・wall/RSS予算も
新rootへ凍結できる。初回値をtoolingの固定最大値とする旧記述はこの追加指示で置き換える。
これは人間が後日選ぶ拡大runの操作経路であり、実行開始や必要データ量の決定を意味しない。

[人間用手順](../../tools/reversi-ai-training/README.md#0054-自前データによるtable32学習サイクル)は
`start_table32.py prepare|run|resume|verify` を使用する。規模・timeout・資源はprepareで凍結し、
設定変更は新rootとする。SIGINT/SIGTERM後も完成単位のatomic stateを照合して再利用し、
同一rootの実行wall予算はattempt間で累積する。最初の20局が10点以上の場合のみ、
人間の明示 `--extend-to-200` で200局へ延長できる。MSEを対戦省略gateにはしない。

tooling検証では共通14ケースのfeature/phase/prediction/digest、D4共有、raw ±15/±16、
丸め順、parameter範囲、旧artifact拒否、TT context分離をfixtureで確認した。
Python全体201件と最終修正後のtable32関連71件、Rust engine28件・AI130件、
workspace Clippy、fmt、GDExtension buildが通過した。
CLIのprepare/run/resume/verifyは `--help` で引数を確認した。
この実装作業で本番prepare、実学習、生成対局、実比較、Oracle診断は開始していない。
fixtureは工程の部品検証であり、実モデルの強さや学習サイクル成立の証拠ではない。

0054 prepareのOracle適格性は、0019 manifestの実行時 `oracle_binary.sha256` ではなく、
Egaroucid 7.8.1、pinned source archive SHA-256
`173af642276216a284498f8d7e32de23dbb9dc6611686c370b0de3eddbc1238b`、profile identity、
source archive由来のbuild/runtimeを検査したruntime setup receiptで確認する。
この条件により、同じ固定sourceから再buildした実行binaryを使える。旧0019 binary digestと
0019/0051/0052/0053の原本inventoryは書き換えず、table32専用adapterが0054のhistorical replay時だけ
旧Oracle entryを照合する。manifest reloadではreceipt、archive/version/profile/path、実runtimeを
再検証する。production/optimizer/evaluation verifierと0053のsource hash契約は変更しない。

後日、人間が開始した実runの保存原本を別タスクでoffline再構成し、工程成立または有効な停止、
20局screeningと許可された200局の結果、coverageと資源の限界を結論として記録する。
それまでは0054計画を保持し、0018入力・試験と採用判断は開始しない。
