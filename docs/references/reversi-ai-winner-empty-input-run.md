# winner-empty-v1 実入力bundle run（0051-20261017-02）

2026-10-17、0051で固定したwinner-empty-v1のproduction入力、baseline、独立Oracle corpus、CLI probeを生成し、全producer出力をoffline再構成した。最終`bundle-verify`も成功したため、このbundleは0037の実pilotをprepareする入力gateを満たす。0037のpilot実行、改善、不成立の判定はまだ行っていない。重み診断や入力完成を対局強度の証拠として扱わない。

## runとproducer identity

- run root: `/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-runs/0051-20261017-02`
- checkout: `/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.worktrees/reversi-adventure@feat-reversi-ai-winner-empty-input-run-retry`
- producer / merged-main commit: `21a7b8dc141e8c729cf64952149c32a5ae8e97a3`（PR #269のRSS修正を含む）
- score contract: `winner-empty-v1`、generator `reversi-ai-random-games-v2`、schema 2、license `CC0-1.0`
- 全量seed: `2026101703`。2048/256/256局、record開始は8 placements、最大128 turns。
- 0018予約: `not-yet-selected`、artifactなし、keys空。存在しないsuiteや開局keysは作っていない。

bundleは上記commitと次のproducer bytesを固定する。全ファイルのidentityと出力閉包はcompletion bundleが保持する。

| producer source | SHA-256 |
| --- | --- |
| `tools/reversi-ai-oracle/oracle.py` | `ab3d618ad7ebcfe20e53711a6feaa6bfb0c9a58ef1c478249ce14e7027c31f4d` |
| `tools/reversi-ai-training/corpus.py` | `fc21945a30213a116fec7fb07dcb2207d08e3ff98cce19c5bdd0116a35e86a15` |
| `tools/reversi-ai-training/input_bundle.py` | `a435b0cf586e965e823629463f6c0880f678e5554bbd489fffe02593b7d7f3e7` |
| `tools/reversi-ai-training/legacy.py` | `636d291b74355196ec296209e57377ec540ea1e5427590d8f79aaaddec50096a` |
| `tools/reversi-ai-training/random_inputs.py` | `cfd477f7ca0608527402215c130fab16ef4b9c8838a6edf2b5760a900ec52361` |
| `tools/reversi-ai-training/reinforcement.py` | `3e5289f4ce0dd0287531b1f2e48e05660547facaca60e95fc74d0b3eff1118b0` |
| `tools/reversi-ai-training/training.py` | `f19bc3da930d52759612de2b4b86f253db5de845635d9177ca2fa0b0774cdd58` |

CLIは`cargo build --release --bin reversi-ai-cli`でbuildし、Cargo.lock SHA-256は`53abb0612fccfbf25258e7faa1788476e7058e6435cc2563655a167f97ee0280`、binary SHA-256は`5663fa9c876d66ed5f7692371a52a20bb7202ed236a4efc1a6265a908d5b0dec`。build receiptは`cli-build/output/build.json`（SHA-256 `ecd0b870c66cfb2d421ebdb0546aa3b40ad016a0caf40062f471a56ebb904438`）。Oracleは`strong-engine-hcap-v1`で、binary SHA-256 `108ca094f4dafa8b51c48811f1783baf491eb25fd2149c02845a2b07df3a794c`、resources 38件のdigest `72e5e7bb3a530352dc01032ea269b9376b2fc4bf45c1e93bccfe5d60fc1ae8fa`。runtime receiptは`oracle-runtime/retry-01/runtime.json`（SHA-256 `f5c577ec9f734bfd806c07d0ccaf1e9e70b3858fb4c8a24ff959e6c3cf2fc986`）。

## stage結果

以下は保存reportのwall/CPU秒と1秒samplingによるpeak RSS。上限に達したstageはない。RSSは瞬間ピークを保証しない観測値である。すべての成功stage reportはmanifest、stdout/stderr、resultおよび出力digestをpinし、後続stageは直前の成功reportを入力としている。

| stage | wall秒（実測 / 上限） | CPU秒 | peak RSS bytes（実測 / 上限） |
| --- | ---: | ---: | ---: |
| calibration-generate | 2.028 / 120 | 0.760 | 6,553,600 / 268,435,456 |
| calibration-verify | 2.025 / 120 | 0.620 | 6,135,808 / 536,870,912 |
| calibration-train | 3.032 / 300 | 1.890 | 24,932,352 / 1,073,741,824 |
| generate | 215.451 / 600 | 213.340 | 643,887,104 / 1,073,741,824 |
| verify | 145.980 / 1200 | 144.500 | 646,934,528 / 2,147,483,648 |
| train | 582.947 / 1800 | 581.060 | 1,696,731,136 / 3,221,225,472 |
| corpus | 16.109 / 120 | 14.650 | 79,261,696 / 268,435,456 |
| oracle | 158.024 / 4200 | 48.400 | 1,486,139,392 / 3,221,225,472 |
| cli-probe | 3.031 / 10 | 1.040 | 123,002,880 / 3,221,225,472 |
| bundle-verify | 381.284 / 2400 | 378.780 | 1,373,990,912 / 3,221,225,472 |

calibrationはseed `2026101701`の4/2/2局で、train/validation/held-outに212/106/104 records（合計422）。三splitすべてにopening/midgame/endgameがあり、各splitは生成reportで再検証済み。calibration baseline artifactのfile SHA-256は`a2adc66b68869cbdeda321c790f148e99a6f031d2a52d61965836fb72bb61062`、内部artifact digestは`98ba109178bdfbf3d66629092c49696ab3960a3f9658e5e46727373263744377`。

全量generator reportは2560局（2048/256/256）、合計133,944 records。splitごとのrecords、phase coverage、target範囲は次のとおり。targetは各ランダム対局の終局winner-empty値を手番側から見たbootstrap教師であり、Oracle教師値ではない。

| split | games | records | opening / midgame / endgame | target範囲 |
| --- | ---: | ---: | ---: | ---: |
| train | 2048 | 107,174 | 26,487 / 49,086 / 31,601 | -64..64 |
| validation | 256 | 13,405 | 3,313 / 6,144 / 3,948 | -48..48 |
| held-out | 256 | 13,365 | 3,314 / 6,120 / 3,931 | -64..64 |

report上の重複数はtrain 115、validation 15、held-out 17。各splitの独立性はbundle verifierが確認した。全量baseline artifact file SHA-256は`23ed5f73d939300cd04b0842ce24e840f8c829e3ee942244a7de56a293dc6875`（内部artifact digest `5acdb66796eec726aea1f5e41bb8ccaf84c052e3b39218b7aeea1cc3b5ff4610`）、trainer report file SHA-256は`b7ccafa07274bc68d39a11b5e861b80d3fb36419fd1b3d68dc27a2aa5caf32d3`（内部report digest `9b6415ec3fad49e1f46351832f7afd0ea7f2d4b0ef90c461911a6348e113a2f2`）。

held-out 13,365行のbaseline診断はweighted MSE `274.4534979424`、MAE `13.3286195286`。同じheld-out targetに対して全予測を0とするzero-weight comparatorは、ストリーミング再計算でMSE `276.0843995511`、MAE `13.3777777778`。baselineとの差は小さく、どちらも予測誤差診断であって対局強度の証拠ではない。artifactには52 stone-phase bucket、3,328 feature maps、227,093個の非zero sparse entriesがある。疎なartifactで省略されたweightは0として扱われる。

corpusはseed `2026101704`、最大256候補局から20/40/48 stonesを各4 root（計12）選定した。全train/validation/held-out 133,944 exposure keysを除外し、予約keysは0。Oracle evidenceは`complete`、12 roots・123 legal child queries・12 golden recordsを保存し、timeoutやroot差し替えを完成入力に混ぜていない。原本closureは38ファイル（evidence、golden、各rootのproblem/stdout/stderr）。

CLI probeは事前固定したvalidation openingでreset acknowledgementと合法手を確認し、応答は`c3`。probe reportにはraw stdout/stderrとbinary/artifact identityが含まれる。

## completion bundleとdigest

すべてcheckout外に保存し、bundleに全stage report、各stage manifest、全producer出力、raw log、Oracle原本、露出keysのdigestを含める。ここではpilot開始に必要な主要pinを示す。`bundle.json`を読むと他の全出力digestとstage receiptを取得できる。

| artifact | run rootからの相対path | SHA-256 |
| --- | --- | --- |
| generator manifest | `full/generator-manifest.json` | `40099e210f9aa2f3fa14403a6fbb28a2b9d7ccc03b97ac4d3c8ff2cdebfc1769` |
| games | `full/generated/games.jsonl` | `1fa195f22ed10212c19877f7238c37a37f22036f65f585ec4abcdea0b859a8dc` |
| train | `full/generated/train.jsonl` | `d88e3c738356016afb364a80cc54bf7f7a4b689c2835f16f530f096c6a737562` |
| validation | `full/generated/validation.jsonl` | `18135cc5b7ebcc98b8078ad9e2c7bbaea4f285d7eb18769e9d740d1327aca1a7` |
| held-out | `full/generated/held_out.jsonl` | `0d23d5bfe659f8c97db77c5cae529f7a0b240657ece37767e7783e47d9bc4267` |
| trainer manifest | `full/generated/trainer-manifest.json` | `e39bcdbd99d08d8452953de63ecb888017504137c11119fd956a828948b355a3` |
| generator report | `full/generated/report.json` | `c45f2a5718a8c959d95664eb50d500cfd43f28d422b858719b32b18738d804d2` |
| baseline artifact | `full/baseline/artifact.json` | `23ed5f73d939300cd04b0842ce24e840f8c829e3ee942244a7de56a293dc6875` |
| baseline report | `full/baseline/report.json` | `b7ccafa07274bc68d39a11b5e861b80d3fb36419fd1b3d68dc27a2aa5caf32d3` |
| corpus | `corpus/corpus.jsonl` | `c391adec8dafde0a7d5610fc4093e60fd5c2aa43a136b8e7f0a2110b8087b584` |
| corpus games | `corpus/games.jsonl` | `f346ad6cf192ed0239711af3fe50ef366240499677c65d2a7e32583ffed4dc73` |
| corpus selection | `corpus/selection.json` | `a2596282d10316e4a944b7242f850966adffc7f3dcc420de491116f22cc80ee1` |
| Oracle evidence | `oracle/evidence.json` | `96db74bc18c9331c73c63517c041dffdc09e9c6ec1ae3b5b7d3c00a52c82071d` |
| Oracle golden | `oracle/golden.jsonl` | `c1242e442ffd7781510cfa10cac75385ad06b660bf1f64078fa573d82fc7de08` |
| CLI probe | `cli-probe/cli-probe.json` | `1ca38ccbe1aa94e116b23f565ecd637f5d819b62f449b4c5e117ee4e0aae46f0` |
| completion bundle | `completion/bundle.json` | `0996da3c4ecfbcf76eeef2ffd7c84072825af450691085b9b5c41ae4f1a09421` |
| bundle verification report | `completion/bundle-verification.json` | `6fb9b75de11cf6777b3a539bbc79407b15901610d4bf2c3f21e7fe4203b8dee2` |
| bundle-verify stage report | `stages/bundle-verify/report.json` | `03c9028dbb61cd83442cc4cf853a5e96333aa0c1d9d5096c2ee415532ab3aed9` |

`bundle-verification.json` reports `input_kind=production`, `strength_inputs=true`, `tooling_only=false`, schema 1, and reservation `not-yet-selected` with empty keys. The bundle digest above is repeated in that verification report. `input_bundle.verify_stage` accepted the final stage report and recursively checked its predecessor reports, resource bounds, pinned inputs, raw logs, and output closure. The stage completed with exit code 0.

## failure and retry history

The first run's corpus stage at `/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-runs/0051-20261017-01/stages/corpus` stopped as `rss-limit` after 3.051 seconds at 351,682,560 observed bytes against 268,435,456. Its `failure.json` SHA-256 is `c26a1b6907f1a4c251f0bbbfd86a87be25d42a34679714460316746509a62ff3`; manifest SHA-256 is `9f137fd2688681af7819024ac9bfe0cd04a6741aacaa2d0bc434cb3d2365f4c3`. That failed original remains preserved. After the streaming corpus repair was merged in PR #269, run02 used the pinned merged producer and a fresh output root; its corpus stage passed in 16.109 seconds at 79,261,696 observed bytes. The failed run was not resumed or overwritten.

## 0037 handoff

The input gate is complete. The next authorized 0037 action is to prepare a new immutable pilot manifest with the verified bundle receipt and pinned CLI, then follow 0037's human-operated run boundary. For example, the manifest can be written beside this run's completion records:

```sh
rtk make pattern-pilot-prepare \
  PILOT_INPUT_BUNDLE=/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-runs/0051-20261017-02/completion/bundle.json \
  PILOT_BUNDLE_VERIFICATION_RECEIPT=/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-runs/0051-20261017-02/stages/bundle-verify/report.json \
  PILOT_CANDIDATE_EXECUTABLE=/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.worktrees/reversi-adventure@feat-reversi-ai-winner-empty-input-run-retry/target/release/reversi-ai-cli \
  PILOT_MANIFEST=/home/yoske/src/github.com/yoskeoka/vibe-coding-workspace/.local/reversi-ai-runs/0051-20261017-02/completion/pilot-0037-manifest.json
```

Preparing or running the pilot is separate from 0051. The pilot still needs all six self-play games, at most 768 deduplicated teacher rows, ten complete candidate pairs/20 comparison games, offline replay, and independent before/after metrics. Only that pilot result can establish improvement or failure; this run does not authorize 0019 production work or 0018 acceptance.
