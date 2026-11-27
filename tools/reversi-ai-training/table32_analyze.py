#!/usr/bin/env python3
"""Analyze a verified full table32 combination using its saved extracted rows."""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import table32_combine as combine
import table32_inputs as inputs
import table32_model as model
import table32_optimizer as optimizer
import table32_store as st
import training


SPLITS = ("train", "validation", "test")
PHASES = range(model.PHASE_COUNT)
TEACHERS = {"project-owned-s0-terminal", "project-owned-s0-depth17"}


def verified_combined(root):
    manifest = st.read(root / "manifest.json")
    st.require(manifest.get("version") == combine.VERSION and manifest.get("coverage") == "full"
               and manifest.get("phases") == list(PHASES), "expected a full table32 combination")
    artifact = model.validate_artifact(st.read(root / "candidate-artifact.json"))
    candidate_digest = model.digest(artifact)
    manifest_digest = st.digest(manifest)
    st.require(artifact == combine.candidate(manifest, artifact["weights"]), "combined candidate provenance differs")
    prepare = st.read(root / "prepare.receipt.json")
    st.require(prepare == st.seal({"manifest_digest": manifest_digest, "candidate_digest": candidate_digest}),
               "combined prepare receipt differs")
    report_path = root / "report.json"
    receipt_path = root / "offline-verification.receipt.json"
    if not report_path.is_file():
        report_path = root / "screening-report.json"
        receipt_path = root / "screening-verification.receipt.json"
    report = st.read(report_path)
    st.require(report == st.seal(report) and report["version"] == combine.VERSION
               and report["manifest_digest"] == manifest_digest
               and report["candidate_digest"] == candidate_digest and report["coverage"] == "full"
               and report["outcome"] == st.match_outcome(report["points"], report["games"])
               and report["status"] == ("awaiting-human" if report["outcome"] == "awaiting-explicit-continue"
                                        else "complete"), "combined report differs")
    st.require(st.read(receipt_path) == st.seal({"manifest_digest": manifest_digest,
               "report_digest": st.digest(report), "prefix_digest": report["completed_prefix_digest"]}),
               "combined verification receipt differs")
    return manifest, artifact, report


def file_identities(record):
    return [(Path(pin["path"]).name, pin["sha256"]) for pin in record["files"]]


def saved_diagnostics(root, report):
    if "phases" in report and "coverage" in report:
        return report
    # Match-era training reports stored this payload in the unit journal.
    # The verified report pins the payload independently of journal layout.
    for path in sorted((root / "units").glob("*.json"), reverse=True):
        entry = st.read(path)
        if (entry.get("phase"), entry.get("unit")) == ("diagnostics", "metrics"):
            value = entry["value"]
            st.require(entry == st.seal(entry) and entry["manifest_digest"] == report["manifest_digest"]
                       and st.digest(value) == report["diagnostics_digest"], f"saved diagnostics differ: {root}")
            return value
    raise training.TrainingError(f"saved diagnostics missing: {root}")


def verified_sources(manifest, artifact, roots):
    pinned = {record["manifest_digest"]: record for record in manifest["source_runs"]}
    st.require(len(pinned) == len(manifest["source_runs"]), "duplicate pinned source")
    phase_sources = {}
    seen = set()
    for root in roots:
        identity, source_artifact, _ = combine.source(root)
        digest = identity["manifest_digest"]
        st.require(digest in pinned and digest not in seen, f"unexpected or duplicate source: {root}")
        seen.add(digest)
        record = pinned[digest]
        # A copy of the source can be supplied from a different directory.
        fields = set(record) - {"root", "files"}
        st.require({k: record[k] for k in fields} == {k: identity[k] for k in fields}
                   and file_identities(record) == file_identities(identity), f"pinned source differs: {root}")
        report_path = root / "report.json"
        if not report_path.is_file():
            report_path = root / "screening-report.json"
        report = saved_diagnostics(root, st.read(report_path))
        diagnostics = {value["phase"]: value for value in report["phases"]}
        for phase in identity["phases"]:
            st.require(phase not in phase_sources
                       and source_artifact["weights"][str(phase)] == artifact["weights"][str(phase)],
                       f"source phase weights differ: {phase}")
            phase_sources[phase] = (root, record, report["coverage"], diagnostics[phase])
    st.require(seen == set(pinned) and set(phase_sources) == set(PHASES), "incomplete source phase coverage")
    return phase_sources


def read_rows(root, coverage, phase, split):
    name = f"{split}-{phase:02d}.jsonl"
    data = (root / "extracted" / name).read_bytes()
    digest = sha256(data).hexdigest()
    st.require(digest == coverage["outputs"][name], f"extracted rows changed: {root.name}/{name}")
    rows = [json.loads(line) for line in data.splitlines()]
    st.require(len(rows) == coverage["phase_rows"][split][str(phase)], f"extracted row count differs: {name}")
    keys = set()
    for row in rows:
        key = row["canonical_key"]
        st.require(row["split"] == split and row["phase"] == phase and model.phase(row["board"]) == phase
                   and row["score_contract"] == model.SCORE_CONTRACT and row["source_kind"] in TEACHERS
                   and type(row["target"]) is int and -64 <= row["target"] <= 64
                   and row["features"] == model.features(row["board"], row["side"])
                   and key == inputs.position_key(row["board"], row["side"]) and key not in keys,
                   f"invalid extracted row: {name}/{row.get('id')}")
        keys.add(key)
    return rows, keys, digest


def occurrences(rows):
    direct = Counter(i for row in rows for i in row["features"])
    expanded = direct.copy()
    for index, count in direct.items():
        expanded[model.reverse_index(index)] += count
    return direct, expanded


def occurrence_summary(counts):
    absent = model.PARAMETER_COUNT - len(counts)
    histogram = {str(count): amount for count, amount in Counter(counts.values()).items()}
    return {"observed_parameters": len(counts), "unobserved_parameters": absent,
            "occurrence_histogram": {"0": absent, **histogram}}


def split_result(rows, weights, float_weights, direct, expanded, data_digest, raw_count):
    return {"integer": optimizer.loss(rows, weights, integer=True),
            **({"float": optimizer.loss(rows, float_weights)} if float_weights is not None else {}),
            "missing_reason": None if rows else "no-saved-rows",
            "rows_sha256": data_digest, "rows_before_deduplication": raw_count,
            "teacher_rows": dict(Counter(row["source_kind"] for row in rows)),
            "side_rows": {side: sum(row["side"] == side for row in rows) for side in ("B", "W")},
            "runtime_feature_occurrences": occurrence_summary(direct),
            "training_parameter_occurrences": occurrence_summary(expanded),
            "nonzero_export_parameters_observed": len(direct.keys() & weights.keys())}


def phase_report(phase, source, table, include_float):
    root, record, coverage, diagnostic = source
    weights = {int(index): value for index, value in table.items()}
    fixed = phase in record.get("fixed_zero_phases", ())
    float_weights = None
    if include_float and not fixed:
        state = st.read(root / "trained-phases" / f"p{phase:02d}.json")
        st.require(state["phase"] == phase and optimizer.state_digest(state) == diagnostic["float_state_digest"],
                   f"final float state differs: {phase}")
        float_weights = dict(zip(state["indices"], state["weights"]))

    splits, previous_keys = {}, set()
    for split in SPLITS:
        rows, keys, digest = read_rows(root, coverage, phase, split)
        st.require(previous_keys.isdisjoint(keys), f"cross-split canonical overlap: {phase}/{split}")
        previous_keys.update(keys)
        direct, expanded = occurrences(rows)
        summary = split_result(rows, weights, float_weights, direct, expanded, digest,
                               coverage["raw_phase_rows"][split][str(phase)])
        if fixed and not rows:
            summary["missing_reason"] = "no-saved-rows-for-fixed-zero-phase"
        if split == "train":
            trained_parameters = expanded.keys()
            if not fixed:
                st.require(diagnostic["counts"] == {str(i): count for i, count in expanded.items()},
                           f"saved training parameter occurrences differ: {phase}")
        summary["observed_in_train_parameters"] = len(direct.keys() & trained_parameters)
        summary["unobserved_in_train_parameters"] = len(direct.keys() - trained_parameters)
        if f"integer_{split}" in diagnostic:
            st.require(summary["integer"] == diagnostic[f"integer_{split}"],
                       f"saved integer loss differs: {phase}/{split}")
        if float_weights is not None and f"float_{split}" in diagnostic:
            st.require(summary["float"] == diagnostic[f"float_{split}"],
                       f"saved final float loss differs: {phase}/{split}")
        splits[split] = summary
    return {"phase": phase, "source_root": Path(record["root"]).name,
            "source_manifest_digest": record["manifest_digest"],
            "fixed_zero": fixed, "nonzero_export_parameters": len(weights), "splits": splits}


def analyze(root, roots, include_float):
    manifest, artifact, combined_report = verified_combined(root)
    sources = verified_sources(manifest, artifact, roots)
    return {"version": "table32-loss-analysis-v1", "candidate_digest": model.digest(artifact),
            "combined_root": Path(root).name, "combined_manifest_digest": st.digest(manifest),
            "combined_report_digest": st.digest(combined_report),
            "saved_match": {key: combined_report[key] for key in ("games", "points", "outcome")},
            "score_contract": model.SCORE_CONTRACT, "target_perspective": "side-to-move",
            "integer_prediction": "sum-raw32/32-round-half-away-from-zero-then-clip-to-64",
            "float_prediction": "clip-sum-to-raw32-range-then-divide-by-32" if include_float else None,
            "loss_units": {"mse": "disc-difference-squared", "mae": "disc-difference"},
            "test_usage": "exposed-diagnostic-exclude-from-final-holdout",
            "phases": [phase_report(p, sources[p], artifact["weights"][str(p)], include_float) for p in PHASES]}


def plot(report, metric):
    from matplotlib.backends.backend_agg import FigureCanvasAgg
    from matplotlib.figure import Figure
    from matplotlib.ticker import MultipleLocator

    figure = Figure(figsize=(10.8, 4.5), dpi=135, layout="constrained")
    FigureCanvasAgg(figure)
    axes = figure.subplots()
    units = "disc difference squared" if metric == "mse" else "disc difference"
    axes.set_title(f"Combined table32 phase {metric.upper()}", loc="left", fontweight="bold")
    axes.set(xlabel="Phase (placed discs)", ylabel=f"{metric.upper()} ({units})", xlim=(-0.5, 59.5))
    axes.xaxis.set_major_locator(MultipleLocator(5))
    axes.grid(axis="y", alpha=0.25)
    if any(phase["fixed_zero"] for phase in report["phases"]):
        axes.axvspan(-0.5, 0.5, color="#b3bcc7", alpha=0.3, label="Phase 0 fixed zero")
    for split, color, marker in zip(SPLITS, ("#27669e", "#bf6300", "#218255"), ("o", "s", "^")):
        series = [p["splits"][split] for p in report["phases"]]
        axes.plot(PHASES, [s["integer"][metric] for s in series], color=color,
                  marker=marker, markersize=3, linewidth=1.15, label=split)
        if report["float_prediction"]:
            axes.plot(PHASES, [s.get("float", {}).get(metric) for s in series], color=color,
                      linestyle="--", alpha=0.8, linewidth=1, label=f"{split} float")
    axes.set_ylim(bottom=0)
    axes.legend(ncol=4, fontsize="small", frameon=False)
    stream = BytesIO()
    figure.savefig(stream, format="png")
    return stream.getvalue()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--combined-root", type=Path, required=True)
    parser.add_argument("--source-root", type=Path, action="append",
                        help="override recorded source paths with all verified source roots")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--include-float", action="store_true",
                        help="include diagnostics for verified final float weights")
    args = parser.parse_args(argv)
    try:
        root = args.combined_root.resolve(strict=True)
        saved = st.read(root / "manifest.json")
        roots = args.source_root or [Path(record["root"]) for record in saved["source_runs"]]
        roots = [path.resolve(strict=True) for path in roots]
        output = args.output_dir.resolve()
        st.require(all(output != source and source not in output.parents and output not in source.parents
                       for source in (root, *roots)), "analysis output overlaps input root")
        report = analyze(root, roots, args.include_float)
        figures = {metric: plot(report, metric) for metric in ("mse", "mae")}
        document = (json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n").encode()
        for name, data in [(f"{metric}.png", data) for metric, data in figures.items()] + [("report.json", document)]:
            st.atomic_bytes(output / name, data)
    except (OSError, ValueError, TypeError, KeyError, ImportError, training.TrainingError) as error:
        parser.exit(1, f"table32 analysis failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
