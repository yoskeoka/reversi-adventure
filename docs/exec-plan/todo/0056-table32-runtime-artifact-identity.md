# 0054の実行時artifact identityを記録する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

0054の実験開始前に、計画時や過去の比較runで使った実行ファイルとの完全一致を要求せず、
実際に使うcandidateとOracle runtimeをprepare時に記録する。記録にはcandidateのsource commitと
binary SHA-256、Oracleのversion/source archive SHA/profile/runtime receiptと解決したbinary・
resource identityを含める。実験を正確に再現・検証するときは、この0054 run固有の記録を使う。

run/resume開始時にはprepare時に記録した同一runのidentityを再検証し、途中で実行物が変わって
いれば停止する。共有利用者間の同時変更・競合や、run中の継続的な再検査は扱わない。
candidate source commitは正確なprovenanceとして記録する値であり、予定commitとの一致gateではない。
OracleはEgaroucid 7.8.1と指定source archive SHA、専用profileを検証し、配布/展開binaryの
historical pathやbinary SHAとは一致を要求しない。

0054の入力再構成を妨げる過去のcandidate/Oracle executable pinだけを互換adapter内で扱う。
0019/0051/0052/0053のmanifest、receipt、report、artifact、inventoryと既存strict validatorは
変更・再sealしない。他の非実行入力digest、採用model/catalog、data/run設定pinは維持する。
この計画PRでは仕様と計画のみを変更し、prepare/run/resume、学習、対局、Oracle診断は実行しない。

Addresses: N/A — 0054のoperator workflow reproducibility correction。既存acceptance issueを閉じない。

## 根拠と対象範囲

- PR #289で用意した0054 toolのprepareが、historical 0052 comparisonに記録されたcandidate CLI SHAとの不一致で停止した。
- 実行前に歴史的binaryを復元する運用は、実際に0054で使うcandidateを正確に記録する目的と合わない。
- Oracleは指定version/source archiveから用意したruntimeを許容し、binary digest/pathは同一runの再現用identityとして記録する。
- 対象は0054の`prepare|run|resume|verify`とそのhistorical input replayだけ。既存の一般validatorの意味を広げない。

## 変更マップ（実装時）

- (MODIFY) `docs/specs/reversi-ai.md` — 0054のcandidate/Oracle runtime identity、historical replay例外、run/resume再検証を規定する（本計画PRで先行更新）。
- (MODIFY) `tools/reversi-ai-training/table32.py` と必要な入力/replay helper — candidate source commit引数を受け、prepare時の実binary SHAと合わせてmanifestへ記録する。commitは形式検証のみとし、既定/予定commitとの比較をしない。
- (MODIFY) 0054 Oracle runtime adapter — version/source archive SHA/profile/receiptを検証し、historical 0019 Oracle binary path/SHAとの一致を要求しない。実際のruntime binary/resource identityとreceipt digestを0054 manifestへ保存する。
- (MODIFY) 0054 historical replay adapter — 0051/0052由来のcandidate executableおよび0019由来Oracle executableの過去identity比較のみを0054入力復元時に迂回する。元manifest/receiptや一般validatorは編集しない。
- (MODIFY) 0054 load/run/resume/verify — prepare manifestに記録されたcandidate commit/SHAとOracle receipt/runtime identitiesを同じrunの実行開始時に再検証する。resumeでも同一identityを要求する。実行中の逐次確認や複数利用者の競合処理は追加しない。
- (MODIFY) `tools/reversi-ai-training/README.md` — candidate source commit変数とCLI引数、実行binary pathを含むprepare/resume手順、identity変更時は新run rootを使う手順を記録する。
- (MODIFY) 関連table32/Oracle adapter tests — 下記受入条件をfixtureで検証する。production run、対局、Oracle solveは起動しない。

## 受入条件

1. 現在のcandidate binaryがhistorical 0052 SHAと異なっていても、source commitを指定してprepareでき、0054 manifestに指定commitと実SHAが記録される。
2. malformed/missing source commit、candidate fileの不在/不正、Oracle version/source archive SHA/profile/receipt不一致はprepareで拒否される。candidate commitを予定値と照合しない。
3. Oracle runtime receiptが指定7.8.1 source archiveとbuild/runtime内容を検証できれば、historical 0019 binary path/SHAと異なっても0054用として受理され、実際のruntime identityが記録される。
4. 0051/0052 source replay時に必要なcandidate executableの過去SHA比較と、0019 Oracle binary path/SHA比較だけを0054 adapterが限定的に扱い、全historical manifest/report/receipt/artifact bytesとdigestを変更しない。
5. 非実行入力digest、採用baseline、catalog、seed、sampling、optimizer、resource settingsなど他のprepare settings/identitiesは従来どおり厳密に照合される。
6. prepare後にcandidateまたはOracle runtime identityが変わった状態でrun/resume/verifyを開始すると拒否される。再現に別binaryを使う場合は新run rootを準備する。
7. `prepare → run → resume → verify`のmanifest/load/replayが同一の実行時identityを通じて整合し、同じhistorical inputでfixture検証できる。

## 検証と完了

- adapter単体fixtureで、異なるcandidate SHAの受理、source/archive/profile境界、限定historical replay、prepare後のidentity変更拒否を検証する。
- strict `production_cycle` / optimizer compare / evaluation validatorの既存境界を変更していないことを確認する。
- workflow lintと適用されるdocs/static checksを通し、0054の実学習・対局・Oracle診断は開始しない。
- 実装PRでは新しいrun rootを使うoperator向けprepare/resumeコマンドを示す。historical rootや入力証跡は変更しない。
- 実測の実験結果を主張せず、本計画は実装PRの準備後に削除する。
