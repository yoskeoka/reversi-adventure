#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: bash run-table32-labels.sh RUN_DIRECTORY COMMAND [ARGS]
  measure RUNTIME_RECEIPT               Measure or resume; print time estimates
  prepare RUNTIME_RECEIPT               Prepare the production manifest
  run PHASE_START PHASE_END [BATCH_START BATCH_STOP]
                                        Start or resume the selected range
  verify [--complete]                   Verify production labels offline

RUN_DIRECTORY and RUNTIME_RECEIPT are absolute paths.
Optional environment settings: JOBS, ATTEMPT_WALL_SECONDS, MAX_RSS_KIB,
PROGRESS_EVERY, LABEL_BATCH_SIZE and LABEL_BATCH_TIMEOUT_SECONDS.
EOF
}

if (( $# < 2 )) || [[ "$1" != /* ]]; then
    usage >&2
    exit 2
fi

run_directory=$1
command=$2
shift 2
tool_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
corpus_root="$tool_dir/../../data/table32-opening-corpus"
measurement_root="$run_directory/measurement-v7.8.1-level21"
production_root="$run_directory/labels-v7.8.1-level21"
tool=(python3 "$tool_dir/table32_labels.py")
limits=(
    --attempt-wall-seconds "${ATTEMPT_WALL_SECONDS:-43200}"
    --max-rss-kib "${MAX_RSS_KIB:-1572864}"
    --progress-every "${PROGRESS_EVERY:-128}"
)

check_measurement_receipt() {
    if [[ ! -f "$measurement_root/manifest.json" ]]; then
        printf '%s\n' 'Run measure before preparing production labels.' >&2
        return 2
    fi
    python3 - "$measurement_root/manifest.json" "$1" <<'PY'
import hashlib
import json
from pathlib import Path
import sys

manifest = json.loads(Path(sys.argv[1]).read_text())
receipt = Path(sys.argv[2]).resolve(strict=True)
pin = {"path": str(receipt), "sha256": hashlib.sha256(receipt.read_bytes()).hexdigest()}
if manifest["source"]["runtime_receipt"] != pin:
    sys.exit("Runtime receipt differs from the measurement manifest. Use its original receipt or a new run directory.")
PY
}

case "$command" in
    measure|prepare)
        if (( $# != 1 )) || [[ "$1" != /* ]]; then
            usage >&2
            exit 2
        fi
        ;;
esac

case "$command" in
    measure)
        if [[ ! -f "$measurement_root/manifest.json" ]]; then
            "${tool[@]}" prepare --corpus-root "$corpus_root" --label-root "$measurement_root" \
                --runtime-receipt "$1" --level 21 --measure-per-phase 3 --timeout-seconds 1800 >/dev/null
        else
            check_measurement_receipt "$1"
        fi
        # Keep the estimate available after a bounded or failed attempt.
        status=0
        "${tool[@]}" run --resume --corpus-root "$corpus_root" --label-root "$measurement_root" \
            --jobs 1 "${limits[@]}" || status=$?
        "${tool[@]}" estimate --corpus-root "$corpus_root" --label-root "$measurement_root"
        exit "$status"
        ;;
    prepare)
        check_measurement_receipt "$1"
        "${tool[@]}" estimate --corpus-root "$corpus_root" --label-root "$measurement_root" |
            python3 -c 'import json, sys; json.load(sys.stdin)["complete"] or sys.exit("Measurement is incomplete")'
        exec "${tool[@]}" prepare --corpus-root "$corpus_root" --label-root "$production_root" \
            --runtime-receipt "$1" --level 21 --batch-size "${LABEL_BATCH_SIZE:-16}" \
            --timeout-seconds "${LABEL_BATCH_TIMEOUT_SECONDS:-7200}"
        ;;
    run)
        if (( $# != 2 && $# != 4 )); then
            usage >&2
            exit 2
        fi
        range=(--phase-start "$1" --phase-end "$2")
        if (( $# == 4 )); then
            range+=(--batch-start "$3" --batch-stop "$4")
        fi
        exec "${tool[@]}" run --resume --corpus-root "$corpus_root" --label-root "$production_root" \
            "${range[@]}" --jobs "${JOBS:-1}" "${limits[@]}"
        ;;
    verify)
        exec "${tool[@]}" verify --corpus-root "$corpus_root" --label-root "$production_root" "$@"
        ;;
    *)
        usage >&2
        exit 2
        ;;
esac
