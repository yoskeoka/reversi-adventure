# ww create が更新前のmainから開始した

2026-10-02、workspace rootから `rtk ww create --repo reversi-adventure feat/reversi-ai-exact-threshold-reuse-assessment` を実行した。
`ww version 0.5.4`。実行pathは `/home/linuxbrew/.linuxbrew/bin/ww`。
`ww cd` は期待するworktree pathを返した。

期待: 最新mainから実行branchを作る。実際: HEADは `8c7b5e1` で、GitHubでは依存0039のPR #248とPR #250が既にmergedだった。
stdoutは通常の `Created worktree at ...` で、古いmainを使った警告はなかった。

実行対象: `yoskeoka/reversi-adventure`。cwd: `/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace`。
変更前に作成worktreeで `rtk git fetch origin`、`rtk git rebase origin/main` を実行して回復した。
worktree/branch作成のraw Git fallbackは使っていない。影響は前提実装が欠けた状態から開始したこと。
0041の実装とは別件であり、wwのbase更新方針と期待するworkspace起動手順を確認する。

2026-10-06にも同じversion/path/cwdで再現した。
`rtk ww create --repo reversi-adventure fix/reversi-ai-exact-cache-correctness`
は通常の作成stdoutを返したが、0043の計画が存在しなかった。
期待はmerged PR #252を含む最新main。`rtk git fetch origin` と作成worktreeでの
`rtk git rebase origin/main` により `2151791` へ更新して回復した。
raw Gitによるbranch/worktree作成は行っていない。影響は計画を読む前の追加同期のみ。
