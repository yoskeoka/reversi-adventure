# 学習入力bundleの生成経路と運用

0050は入力の生成経路を再現検証するtoolingの実装である。実2560局の生成、
baseline再学習、実Oracle解析は0051で人間が起動する。入力完成、0037の改善、
0019 freeze、0018達成の結果をこの記録から推定しない。

## 信頼範囲

署名、承認ファイル、鍵、外部allowlistは使わない。レビュー済みのmerged-main
producerをclean checkoutで使用した信頼するローカル人間操作を対象とする。
Git ancestryと保存producer bytesを照合し、全対局とsplitを原本producerで再生成し、
trainerのbaseline/reportを再構成する。SHAは同じbytesの照合であり、悪意ある生成者の
自己申告を認証するものではない。任意labelやverified boolはpilot gateを通さない。

Oracle rootは独立random完成局からscoreを見る前に固定する。全合法手childのproblem、
mapping、argv/cwd、raw stdout/stderr、終了状態、runtime/resourcesの実行前後SHAを保存する。
offline入口は既存parserでgoldenを再構成し、CLIもOracleも起動しない。
本番runtimeは既存の固定archive/source照合・build・version確認を通したreceiptを保存する。
bundleはarchive原本からsource identityを再構成し、receiptとrawのbinary/resourcesを照合する。
任意のfake binaryへprofile名を付けた入力は、本番件数でもstrength gateを通らない。
random終局教師、Oracle child値、0037のbaseline AI継続教師は別の値である。

## 保存と再実行

generator directoryには既存verifierが要求する6ファイルだけを保存する。
凍結prepare manifest、stage logs、baseline、corpus/Oracle、CLI probe、completion bundleは
兄弟directoryに置く。生成後のrecord counts/SHAを新trainer-stage manifestへpinし、
既存manifestを後から書き換えない。stage completion reportは検証後に最後に保存する。

Linux runnerはprocess group全体をwall/観測RSSで停止する。RSSは1秒samplingであり、
瞬間最大値の厳密な保証ではない。metric取得不能は失敗とする。CPU/wall/RSS、
raw出力、失敗/中断原本を保持する。失敗stageは新しい出力先で最初からやり直す。
完成検証済みの前stageは再利用できるが、途中game/trainer/Oracleのresumeはない。
SIGTERMもgroup停止・回収と失敗記録を通す。pilotには最終`bundle-verify` stageの
成功receiptをbundleとは別にpinし、bundle/CLI identityと固定資源予算を再検査する。
実際の上限と進捗形式は[仕様](../specs/reversi-ai.md#training-input-bundle-0050)、
予算と実run手順は[0051](../exec-plan/todo/0051-reversi-ai-winner-empty-input-run.md)を参照する。

## 工程の順序

0050マージ後の新worktreeでsource/Cargo.lock/build recipe/CLI SHAとOracle runtimeをpinする。
人間が8局calibrationのgenerate、verify、trainを個別起動して観測値を保存する。
成功後に別seedの2048/256/256局をgenerate、verify、trainする。三splitを除外した
独立12-root corpusを固定してからOracleをroot単位で解析する。完了原本をoffline検証し、
CLI probeとcompletion bundleを保存する。具体的コマンドは[README](../../tools/reversi-ai-training/README.md)。

0018 suiteは候補選定後に作る。現時点は`not-yet-selected`と空keysを保存する。
将来実suiteが存在する場合のみversioned artifact/path/digestとnonempty keysをpinする。
bundleのtrain/validation/held_out/Oracle root/child、pilotのopening/decision/terminal、
0019の露出keysを後段0018へ渡し、採用開局rootのD4衝突を拒否する。

完成したproduction bundleを0037新schemaのmanifestへpinして、全6局、768行以下、
10完全ペア20局と独立指標を検証した時だけ改善/不成立を記録できる。
縮小fixtureと旧pilot schemaは常にtooling。`production_authorized=false`を維持する。

## Tooling検証

bounded fake producer/Oracle/CLIによる反復再現、保存応答の再解析、改変・欠損の拒否、
resource停止と診断、旧pilot互換をPython testsで検証する。実runの測定値は0051で別記する。

2026-10-15の実装検証では、Oracle 53 tests、benchmark 171 tests、Rust engine/AI
151 tests、fmt、workspace Clippy（warnings denied）、Godot bridge buildを通した。
training全79 testsのうち78件は全体実行で成功し、1件は改変fixtureがimmutable保存の
上書き禁止で停止したため、別pathの偽bundleへ参照を差し替える手順へ修正した。
修正後の対象testは、small bundleからpilotへの接続、offline検証、任意verified flagの
拒否まで成功した。本体sourceの修正は不要だった。
関連するpilot全23 testsも修正後に再実行して成功した。
PRレビューで指摘されたSIGTERMと最終資源gateの抜けを修正し、bundle全7 testsと
監督全5 tests（実SIGTERMのgroup停止・回収・handler復元を含む）を再検証した。
receiptを必須にしたpilot全24 testsも成功し、欠損・改変・失敗・別stage receiptの
拒否と旧v1互換を確認した。
これらは縮小入力とfake runtimeによるtooling証拠であり、本番入力や強さの証拠ではない。
