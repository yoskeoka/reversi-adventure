# corpus除外局面の読込を256MiBの予算内に収める

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的・承認

0051の実corpus stageが3.051秒、観測RSS351682560 bytesで256MiB上限に達した。
ユーザーの「修正をその場で加えることができるならして」により、この限定修正を直接実装する。
上限・seed・入力identityは変更しない。0051の入力完成とは別に修正PRを準備する。

## 参照と変更

- (MODIFY) `docs/specs/reversi-ai.md` input bundle契約: splitを逐次読み込む。
- (MODIFY) `tools/reversi-ai-training/training.py:91-109`: JSONLの逐次readerと既存list API。
- (MODIFY) `tools/reversi-ai-training/input_bundle.py:630-640`: corpus除外keysだけを保持。
- (NEW) reader診断・D4一致・資源上限付き合成fixtureの回帰検証。
- (MODIFY) training README: 旧runを保持し、新merged producerで再実行する制約。
- (DELETE) 本計画: 修正検証とPR準備後。0051は未完了のまま残す。

## 手順・検証

仕様→逐次reader→corpusの利用変更→既存Python checksと回帰検証。
合成fixtureで全量相当134021行の読込と12 root選定・offline再構成を
256MiBのprocess上限内で検証する。実データ生成・学習・Oracleは起動しない。
list readerとの出力・診断一致、非finite/非object/後続不正行、D4除外を確認する。
sourceの同一性検査は維持し、旧runを修正producerへ偽装しない。

## Addresses

- N/A。
