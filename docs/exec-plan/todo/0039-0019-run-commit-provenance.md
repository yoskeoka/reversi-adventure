# 0019の実行checkout commitを成功証拠に記録する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0019の一括実行を、人間が用意した最新`main` checkoutから通常起動できるようにする。0051 bundleに記録されたproducer source hashと実行側の現在コードを一致させる事前条件を外す。報告されたエラーは、0019で更新された`oracle.py`と`reinforcement.py`が0051 producerのhashと異なるために発生した。

0051 bundle・成功済み最終`bundle-verify` receipt・全入力artifactのdigestと意味検証は維持する。コードsource hashは0019実行のadmission gateに使わない。起動時にcheckoutの`git rev-parse HEAD`を取得し、manifestと成功reportに実行commitとして記録する。このSHAは実行後のprovenanceであり、あらかじめ期待値を指定したり、過去producerのcode hashと照合したりする条件ではない。resumeは既存runのmanifestに記録したcommitを継続し、異なるcommitへ切り替える場合は新run rootを使う。人間のproduction runは本計画の実装/fixture検証では開始しない。

0051-20261017-02 bundleはproducer source commit `21a7b8dc141e8c729cf64952149c32a5ae8e97a3`を記録する。再現時、active `oracle.py` はproducer期待値`ab3d618ad7ebcfe20e53711a6feaa6bfb0c9a58ef1c478249ce14e7027c31f4d`と異なり、active `reinforcement.py`も期待値`3e5289f4ce0dd0287531b1f2e48e05660547facaca60e95fc74d0b3eff1118b0`と異なっていた。現行契約はこのsource hash差をbundle/artifact検証より前に拒否していた。

## 参照

- `docs/specs/reversi-ai.md` — `### One-command 0019 production execution` と `## Production reinforcement batch and Oracle distance (0019)`。0051 bundle消費、入力検証、失敗境界、offline verificationのblack-box契約。
- `tools/reversi-ai-training/input_bundle.py:74-112,835-856` — `verify_source`, `verify_bundle`, `verify_for_pilot`。現行producer source equality gateと、維持するreceipt/artifact照合。
- `tools/reversi-ai-training/production_cycle.py:56-62,128-156,255-280` — code source hashes、production manifest準備時とoffline revalidation時の0051 bundle検証。
- `tools/reversi-ai-training/pilot.py:175-190,296-316` — shared `bundle_evidence` と bounded pilot input verification。0019の修正がbounded pilotの6/20/0経路を変えないこと。
- `tools/reversi-ai-training/tests/test_pilot.py` — existing `bundle_stub` verifier mock and production execute/resume tests; extend this suite with latest-checkout provenance cases.
- 0051 completion artifacts `bundle.json` と `stages/bundle-verify/report.json` — producer checkout/source commit、source digests、成功receiptの具体例。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — producer source hashを0019実行条件にしないこと、入力digest/receipt検証、実行checkout commitのmanifest/report記録とresume境界を定義する。
- (MODIFY) `tools/reversi-ai-training/input_bundle.py` — 0019 consumption向けに、producer code hash equalityと入力artifact/receiptの検証を分離する。0051生成・standalone verifierの既存strict契約は維持する。
- (MODIFY) `tools/reversi-ai-training/production_cycle.py` — latest mainのcode hashを検査して停止せず、実行commitをmanifest/reportに記録する。初回・offline verificationは現在のコードで同じbundle/receipt/artifact検証を行う。
- (MODIFY) `tools/reversi-ai-training/tests/test_pilot.py` と関連fixture — 既存の`bundle_stub` verifier mockを拡張し、producer code hashが異なるbundleの成功、artifact/receipt改変の拒否、successful reportの実行commit、offline再検証、resume commit境界を確認する。
- (DELETE) `docs/exec-plan/todo/0039-0019-run-commit-provenance.md` — 実装PRのverificationとPR準備後に削除する。

## ブラックボックス契約と作業

1. 0019はbundleを生成したproducer checkoutを要求せず、最新`main` checkoutのcurrent verifierでbundle、successful final `bundle-verify` receipt、候補CLI、baseline、corpus、golden、validation、held-outのdigestと意味整合性を検証する。producer source commit/hashはbundleに残る来歴metadataとして扱い、active sourceとの一致を要求しない。
2. 0051 bundle/receiptのdigest、receipt成功状態、production/strength eligibility、全artifact identityの検証はfail-closedで維持する。省くのは実行コード/検証コードのproducer source SHA一致gateであり、データartifactのhash検証ではない。
3. 起動時に実行checkoutのcommit SHAを一度取得し、0019 manifestへ記録する。成功時のfinal reportにも同じSHAを含める。SHAがあらかじめ指定した値や0051 producer commitと異なることを理由に起動を拒否しない。offline verifierはmanifest/report間のcommit一致を検証するが、その時点のcheckout SHAとの一致は要求しない。
4. resumeは既存manifest・counts・settings・phase receipts/output digestsに加えて、実行開始時に記録したcommitを継続する。別commitへ更新した場合は新run rootで開始する。source file SHA一覧の事前検証やpinned checkoutの準備は要求しない。
5. 対象は0019 run provenanceの簡素化に限る。人間がproduction commandを開始/待機/監視すること、0051入力を再生成すること、Oracle profile・学習方式・count defaultsを変更することは含めない。

## 依存関係と順序

- 仕様を先に更新し、次にcode identity gateとbundle data verificationの分離、run commit recording、offline/resume境界、fixture testsを実装する。作業は順次実施し、並列作業はない。
- External issue: N/A — linked issueはない。

## 検証

- producer code hashが現在の実行checkoutと異なるfixtureでも、bundle/receipt/artifact digestと意味検証が成功すれば0019 manifestを作成できることを確認する。
- bundle、successful receipt、CLI、baseline/corpus/golden/validation inputsを改変した場合は引き続き拒否する。
- successful final reportのcommit SHAがmanifestに記録した実行checkout SHAと一致し、別commitからのresumeを拒否することを確認する。
- 0051 receipt、bundle、CLI、manifest、phase outputを改変したケースが引き続き拒否される。
- bounded pilot 6/20/0のfixture behaviorと既存のresume/retry contractsに回帰がないことを確認する。
- 関連Python test、`rtk make pattern-training-test`、workflow lint、`rtk git diff --check`を実行する。production runは起動しない。
