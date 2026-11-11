# 部分学習済みtable32の結合と独立評価

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了境界

人間が別々に実行した部分学習の成果を保持し、選択したphaseを一つの候補に結合して、途中段階と全60 phase完成後の双方で強さを評価する。入力元の学習や対局を再実行せず、結合と評価の証拠を別rootに保存し、実行中断から再開できる。実装完了はfixtureによる結合・評価・offline検証と、人間が使える手順まで。実学習・実対局・Oracle診断をagent/CIは開始・監視しない。0054の実験結果の独立検証・結論は別途残り、0054計画は削除しない。0019採用モデル、Playground既定、0018受け入れは変更しない。

Addresses: N/A — 0054の操作経路の追加であり外部issueを閉じない。

## 背景と判断

2026-11-12、人間は複数の部分学習を進め、揃った後に全体の強さを評価したいと指示した。phase 40–49の既存root `0054-20261111-partial-01` はoffline verify済みで、20局6.5点、`not-improved-at-pilot-scale`。これはその部分候補の比較結果であり、結合候補の強さを予断しない。保存済み成果の再利用を許し、過去の探索や対局を再実行しない。

各phaseは独立に初期化・学習され、整数表を結合できるが、各runの出典と評価への露出を保持する必要がある。単一runを装ったJSON手編集や、既存runの対局点の流用は採らない。全phaseを一度に再学習する代替案は、既に得た成果を活かす目的に合わない。人間は、全60 phase完成後だけでなく途中の結合候補の評価にも対応する方針を選んだ。

## 正確な既存参照

- `docs/project-plan.md` のリバーシAI要件、`docs/design-decisions/core-beliefs.md`、`docs/design-decisions/adr.md` の2026-11-01 table32隔離判断。
- `docs/exec-plan/todo/0054-reversi-ai-next-method-experiments.md` — 0054の教師・資源・評価と保存済み証跡を信頼する方針。
- `docs/specs/reversi-ai.md` の project-owned table32 pilot と部分学習契約、`tools/reversi-ai-training/README.md` の0054操作手順。
- `tools/reversi-ai-training/table32.py:141-153,175-182,417-461,601-608,650-691` — 部分phaseの制限、生成、独立学習、export、露出と比較。
- `tools/reversi-ai-training/table32_model.py:99-173`、`rust/reversi-ai/src/eval/table32.rs:173-185` — artifact identity・provenance・phaseとfallback。
- `tools/reversi-ai-training/table32_import.py:49-70` — exact25からexact20への再利用は対象phaseが40以降に限る。
- `tools/reversi-ai-training/table32_store.py:149-155`、`table32_verify.py:49-77` — 20→200 gateとoffline replay。

## 仕様と実装の要件

1. 部分runは別rootで生成・学習・exportできる。評価を後回しにする明示操作を追加し、phase 0–11のみも学習・検証可能にする。既存の評価可能な部分runとそのresumeを壊さない。未評価の完了を対局成功と表示せず、結合に必要な完了状態と検証receiptを定義する。序盤の生成負荷、局数、学習step、時間・資源をoperatorが選べるよう維持する。
2. 結合prepareは新規rootで、各入力rootの保存済み完了証跡・artifact・manifest・必要な露出情報を読み取り、phaseごとの入力選択とdigest、format/catalog/score/scale、baseline、教師・生成条件、producer、設定を固定する。既存のverify済み `0054-20261111-partial-01` を実際に受け入れられることをfixtureに加えてread-only契約として明記する。各入力の来歴を合成manifestへ記録し、既存単一入力のprovenanceを偽装しない。古い探索・対局・学習を再実行せず、保存された完了証跡を信頼する境界と、今回参照するファイルの整合性・意味互換性の確認を明示する。not-improvedの部分候補も明示選択できる。
3. 同じphaseを複数入力が持つ場合は自動選択せず拒否するか、明示的なphase→入力指定を必須とする。欠損ありはpartialとして既存の後方最近傍とS0 fallbackを明示し、60 phase全被覆のみfullとして扱う。結合artifactは既存loaderの意味とdigest検証を満たし、独立した合成manifestのdigestにより全入力へ遡れる。source rootを変更せず、再実行で上書きしない。互換性不足、入力変更、未知の由来、重複・欠損に関する不正は明確に停止する。
4. 評価は結合候補ごとの新しい独立openingでS0と20局を実施し、初回10点未満は終了、10点以上は人間の明示指示で200局、200局100点超のみpromising。各入力の生成・train/validation/test・import・既存比較などの露出集合と0018予約局面を合算し、新openingを除外する。対局中の偶発重複も記録する。途中候補と全phase候補の探索profile・fallback・範囲をreportに記録し、既存partial深さ4と従来full深さ12の差を隠さない。過去の個別評価を合算候補の結果として再利用しない。
5. manifest、unit receipt、生成候補と比較結果を固定して中断再開し、設定や入力変更は新rootとする。attemptごとの時間・資源設定と累積、完了unit・総数・phase・進捗・停止理由を記録し、既存0054の進捗形式とrate制御を踏襲する。offline verifyは結合元と合成結果の対応、露出と対局、gate、reportの整合性を再構成し、trainer・candidate CLI・Oracleをspawnしない。原本を変更しない。
6. 複数部分runはfull方式の早期labelやpreflightを自動的に満たさない。60 phaseを揃えても従来のfull pilotと同一の学習条件や強度を主張せず、reportに学習設定の違いを記録する。自動採用・0018合格・実験完了は意味しない。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 上記の観測可能な契約をコードより先に記載。
- (NEW) `tools/reversi-ai-training/table32_combine.py` と対応tests — 結合manifest、来歴、候補、評価とoffline検証。既存構造に合わせ分割可。
- (MODIFY) `tools/reversi-ai-training/start_table32.py`, `table32.py`, `table32_model.py`, `table32_verify.py`, 必要な共有moduleとtests — 学習のみの完了、互換性、評価と再開。
- (MODIFY) 必要な場合 `rust/reversi-ai/src/eval/table32.rs` とCLI/tests — 正当な結合provenanceとpartial/fullのruntime契約。
- (MODIFY) `tools/reversi-ai-training/README.md`, `Makefile` — 新旧rootの保存と人間向けprepare/run/resume/verify、全phase・途中評価、制約。
- (DELETE) 本計画のみ、tooling検証・PR準備完了後。0054計画・実原本は保持する。

## 実行順序と検証

1. specを更新し、既存runを変更せず新rootと入出力identityを定義する。次に学習のみ・序盤phaseの出口を追加する。
2. 保存証跡のread-only取込、phase重複・欠損・互換性の判定、partial/full exportを実装する。次に全入力の露出集合を使う独立評価、資源制限・resume・offline verifyを実装する。これらは仕様に依存するため順次実行する。
3. 小さなfixtureで既存形式と学習のみ形式の結合、not-improved入力、0–11、60 phase、欠損fallback、重複、破損・入力変更・非互換、対局openingの除外、20/200 gate、途中停止とresume、offlineで外部process不使用を検証する。比較点は再構成し、偽のprovenanceを拒否する。
4. 現存0054 rootのread-onlyの取込互換性を、学習・対局・Oracleを起動せず確認する。必要な操作は小さく有界にし、元rootの変更を避ける。Python関連tests、Rust対象tests・clippy・fmt、workflow lintを実行する。実際の学習結果・強度の証拠とは扱わない。
5. 人間向けコマンドに入力root・phase対応・局数・学習量・attempt時間・resume・verifyを記載し、結果の引渡しを明確にする。実原本が必要な場合は人間による後日の実行とする。
