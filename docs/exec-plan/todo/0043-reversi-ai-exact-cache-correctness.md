# 完全読みの手番間再利用を停止する

> **Execution**: Use `/execute-task` to implement this plan. After implementation is complete, use `/review-task` to prepare and create the PR.

## 目的と完了条件

完全読みが最善値+4を報告しながら値+2の手を返す0041の反例を受け、
原因修正まで手番間のexact cache再利用を停止する。CLIだけでなく共有Rust AI、
AiPlayer、Godot、Playground、自己対局の既定経路を保護する。
既存の閾値16も停止対象であり、深度8の固定棋譜の成功を一般的な正確性保証にしない。

この計画は安全措置だけで完了する。root/PVの原因修正は0044、縮小した検証は0045、
採用と設定/時間予算の判断は0040に分ける。長い全局計測を完了条件に含めない。

## 参照

- [PR #251](https://github.com/yoskeoka/reversi-adventure/pull/251) — 0041の固定証拠、棋譜、独立Oracle。
- `rust/reversi-ai/src/search/mod.rs:167-240,312-320` — `analyze_with_budget`, `search_with_budget`, `new_game`, `clear_exact_cache`。
- `rust/reversi-ai/src/bin/reversi-ai-cli.rs:67,280-291` — 既定game scopeとturn消去。
- `rust/reversi-ai/src/player.rs:17-35` — `AiPlayer::new`, `think`。
- `rust/reversi-godot/src/bridge.rs:186-210` — 製品側の共有AI呼び出し。
- `docs/specs/reversi-ai.md:690-743` — 表のproof/手番視点、CLI scope、本番manifest、局開始reset。
- `tools/reversi-ai-training/reinforcement.py` — `prepare/run/verify` の探索設定・CLI identity。

## 変更マップ

- (MODIFY) `docs/specs/reversi-ai.md` — 手番間再利用停止、実効scope、旧manifestの扱いを先に定義。
- (MODIFY) `rust/reversi-ai/src/search/mod.rs` と関連tests — 公開decision境界でexact tableを消去。
- (MODIFY) `rust/reversi-ai/src/bin/reversi-ai-cli.rs` と関連tests — 既定turn、game指定の一時拒否。
- (MODIFY) `tools/reversi-ai-training/reinforcement.py` と関連tests — 新規prepare/runの実効turnを固定。
- (MODIFY) `tools/reversi-ai-benchmark/whole_game.py` と関連tests — 現行binaryのgame計測は準備段階で拒否。
- (MODIFY) `tools/reversi-ai-benchmark/prepare-whole-game-measurement.py` と関連tests — 停止中のgame条件を事前検証で拒否。
- (NEW) `docs/references/reversi-ai-exact-cache-correctness.md` — 停止範囲、CLI/source digest、短い確認結果。
- (MODIFY) `docs/exec-plan/todo/0044-reversi-ai-exact-cache-correctness-repair.md` — 安全措置の証拠を接続。
- (DELETE, 完了時) 本計画。

## ブラックボックス契約と作業

1. `search_with_budget` と `analyze_with_budget` の各公開呼び出しの開始時にexact tableだけを
   一度消去する。通常TTは保持する。再帰探索と一回のAdvisor候補比較の内部では表を利用し、
   全cacheを無効化する変更や探索/評価の改変を混ぜない。
2. 通常CLIはturnを既定にする。`--exact-cache-scope game` は探索開始前に明確な理由で拒否し、
   gameと記録しながら実際にはturnとして動く状態を作らない。0044で修正後に診断用途だけを再開する。
   CLI以外の共有APIも同じ停止条件を満たすことを小さい呼び出しfixtureで確認する。
3. 自己対局の新規prepare/runは実効turnと停止policy、CLI digestを固定する。
   旧manifestを現行binaryで再開・採用しない。旧binary/manifestで作った完成reportのoffline検証は
   元の契約で保持し、停止措置を過去の測定へ遡及して適用しない。
   新規manifestの識別形式が変わる場合はversionを上げ、旧形式を黙って書き換えない。
4. `new_game` の通常TT/exact/context消去とacknowledgementは維持する。
   共有AIの複数decision、Advisorの複数呼び出し、局開始resetを少数局面で確認する。
   本番freeze/学習開始は0040の採用条件に従い、停止措置だけで性能改善や採用完了を宣言しない。

## 依存関係と順序

- PR #251のマージ後に実行する。証拠を参照して、spec→共有AI/CLI→manifestと準備経路→短い確認→PRと記録の順に進める。
- 0044は本計画のマージ後。0043の完了に0044/0045の完了を要求しない。
- 過去の0041 producer、固定manifest、棋譜、失敗証拠は変更しない。

## 検証

- 同じengineの連続decisionがfresh exact tableの最善値/選択手と一致する小さいfixture。
- decision開始時にexact tableが消え、一回のsolve内部では利用できること。通常TTは消えないこと。
- CLI既定turn、明示game拒否、Advisor/AiPlayer経路、`new_game`、新旧manifestの拒否/検証境界。
- 該当Rust/Python tests、Clippy、GDExtension build、workflow lint、diff check。
- 全局対局、Oracle同士対局、性能再測定は起動しない。

## Addresses

- N/A
