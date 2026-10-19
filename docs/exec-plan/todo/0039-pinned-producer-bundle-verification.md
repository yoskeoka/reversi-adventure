# 0019で0051 bundleをproducer固定toolingで再検証する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

0019の一括実行を、0051 bundleを生成したproducerの固定toolingで検証できるようにする。現在の0019 checkoutでは`oracle.py`と`reinforcement.py`が0051 producer以後に更新されているため、0019の更新を必要とする実行コードと、0051のproducer同一性を要求する検証コードが同じcheckoutを使うと、実入力の検証前に停止する。実際に報告された`active verifier differs from frozen producer`を解消し、作業ディレクトリを変えずに人間が0019の一括コマンドを開始できる状態を完了条件とする。

0051 bundleのproducer source identity・最終`bundle-verify` receipt・全artifact digestの検査は一切緩和しない。検証はbundleが固定するproducer commitとtoolingで行い、その成功結果を0019 manifestとoffline verifierが同じように再検証する。0019の実行コードidentityは別にmanifestへ固定する。人間のproduction runは本計画の実装/fixture検証では開始しない。

0051-20261017-02 bundleはproducer source commit `21a7b8dc141e8c729cf64952149c32a5ae8e97a3`を固定する。今回の再現では、active `oracle.py` は期待値`ab3d618ad7ebcfe20e53711a6feaa6bfb0c9a58ef1c478249ce14e7027c31f4d`に対し`8a90640deccb5ac78786d00998003beb5400fadc68814a64d5ae8876baa21626`、`reinforcement.py`は期待値`3e5289f4ce0dd0287531b1f2e48e05660547facaca60e95fc74d0b3eff1118b0`に対し`3a3df179b78fbb54aa8d393473e3ff78b2d0b4da0181cd91954c803a1e7f48ef`となり、現行検証のproducer source照合に失敗した。`input_bundle.py`自身は期待値と一致している。

## 参照

- `docs/specs/reversi-ai.md` — `### One-command 0019 production execution` と `## Production reinforcement batch and Oracle distance (0019)`。0051 bundle消費、入力検証、失敗境界、offline verificationのblack-box契約。
- `tools/reversi-ai-training/input_bundle.py:74-112,835-856` — `verify_source`, `verify_bundle`, `verify_for_pilot`。producer commit/source hashesとreceipt/artifactを照合する現行契約。
- `tools/reversi-ai-training/production_cycle.py:128-156,255-280` — production manifest準備時とoffline revalidation時の0051 bundle検証。
- `tools/reversi-ai-training/pilot.py:175-190,296-316` — shared `bundle_evidence` と bounded pilot input verification。0019の修正がbounded pilotの6/20/0経路を変えないこと。
- `tools/reversi-ai-training/tests/test_pilot.py` — existing `bundle_stub` verifier mock and production execute/resume tests; extend this suite with pinned-checkout cases.
- 0051 completion artifacts `bundle.json` と `stages/bundle-verify/report.json` — producer checkout/source commit、source digests、成功receiptの具体例。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 0019のbundle再検証に使うproducer checkout/tool identity、fail-closed条件、manifest/offline verifierの一致を規定する。
- (NEW) `tools/reversi-ai-training/pinned_bundle_verifier.py` — 隔離subprocessでbundleに記録されたproducer checkoutから、そのcheckoutの未変更`input_bundle.py`とproducer modulesを読み込み、検証結果をcanonical JSONで返す。
- (MODIFY) `tools/reversi-ai-training/production_cycle.py` — manifest準備とoffline再検証の両方を新helper経由にし、0019 execution source identityとproducer verifier identityを別々に記録する。frozen producerの一部である`input_bundle.py`は編集しない。
- (MODIFY) `tools/reversi-ai-training/tests/test_pilot.py` と関連fixture — 既存の`bundle_stub` verifier mockを拡張し、current 0019 sourceのproducer driftを含む成功、producer sourceの改変/欠落を拒否する失敗、offline再検証を確認する。
- (DELETE) `docs/exec-plan/todo/0039-pinned-producer-bundle-verification.md` — 実装PRのverificationとPR準備後に削除する。

## ブラックボックス契約と作業

1. 初回`input-verification`と`offline-verification`は、0051 bundleが記録したproducer checkout/source commitの検証toolingを隔離processで使う。検証側はproducer identity、全`producer_sources`、bundle本体、successful final `bundle-verify` receipt、CLI/baseline/corpus/golden等のpinを従来どおり再構成する。
2. 0019 checkoutの更新済み`oracle.py`/`reinforcement.py`は0019対局に使い、0051 bundleのproducer replayへ混在させない。verifierのloaderやsubprocess境界が任意コード/別checkoutへ黙ってフォールバックしないよう、producer path・commit・全source digestを照合してmanifestへ記録する。frozen producerの`input_bundle.py`やproducer modulesを現行checkoutのファイルへ更新してはならない。
3. pinned checkoutやsource filesが利用不能/不一致、receiptが不成功、bundleやCLI digestが変化している場合はproduction phase開始前に拒否し、エラーにproducer checkoutと不一致ファイルを含める。verifier起動失敗ではrun rootを作らない。
4. 0019 manifestのsource hashes、phase receipts、selected candidate条件、count/resume、最終reportのbyte-for-byte offline verificationは維持する。更新前の失敗はrun evidenceを作らず、実runの失敗は既存規則に従いimmutableな試行として保存する。
5. 対象はこのverifier routing不具合に限る。人間がproduction commandを開始/待機/監視すること、0051入力を再生成すること、Oracle profile・学習方式・count defaultsを変更することは含めない。

## 依存関係と順序

- 仕様を先に更新し、次にpinned verifier routing、manifest/offline replay、fixture testsを実装する。作業は順次実施し、並列作業はない。
- External issue: N/A — linked issueはない。

## 検証

- 実bundleと同じsource identityを使い、active 0019の`oracle.py`/`reinforcement.py`がproducer bytesと異なっていても、pinned producer verifierで入力検証とoffline再検証が一致するfixtureを確認する。
- pinned checkout/source commit/source fileを欠落または改変した場合、production phase/run-root作成前に診断可能なエラーで拒否する。
- 0051 receipt、bundle、CLI、manifest、phase outputを改変したケースが引き続き拒否される。
- bounded pilot 6/20/0のfixture behaviorと既存のresume/retry contractsに回帰がないことを確認する。
- 関連Python test、`rtk make pattern-training-test`、workflow lint、`rtk git diff --check`を実行する。production runは起動しない。
