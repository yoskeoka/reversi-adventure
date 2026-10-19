"""Bounded fixture provenance, immutable stages and fail-closed supervision."""
import contextlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

TOOL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOL))
import input_bundle as bundle
import random_inputs
import training
from legacy import producer


def frozen_checkout(directory):
    checkout = directory / "source"
    checkout.mkdir()
    for name in bundle.PRODUCERS:
        destination = checkout / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle.ROOT / name, destination)
    shutil.copyfile(bundle.ROOT / "Cargo.lock", checkout / "Cargo.lock")
    (checkout / ".gitignore").write_text("__pycache__/\ntarget/\n")
    def git(*args):
        subprocess.run(["git", *args], cwd=checkout, check=True, capture_output=True)
    git("init", "-b", "main")
    git("config", "user.name", "Fixture")
    git("config", "user.email", "fixture@example.invalid")
    git("add", ".")
    git("commit", "-m", "Frozen fixture producer")
    git("update-ref", "refs/remotes/origin/main", "HEAD")
    spec = importlib.util.spec_from_file_location("fixture_input_bundle", checkout / "tools/reversi-ai-training/input_bundle.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    identity = bundle.source_identity(checkout)
    return checkout, module, identity


def build_small_bundle(directory, cli=None):
    """Real tiny producers and saved fake runtimes; verifier itself stays unmocked."""
    checkout, frozen_bundle, identity = frozen_checkout(directory)
    source_dir = checkout / "tools/reversi-ai-training"
    digests = {name: identity["producer_sources"][f"tools/reversi-ai-training/{name}"]
               for name in ("training.py", "reinforcement.py", "random_inputs.py")}
    unreserved = {"state": "not-yet-selected", "artifact": None, "keys": []}
    if cli is None:
        cli = checkout / "target/release/reversi-ai-cli"
        cli.parent.mkdir(parents=True)
        cli.write_text(f"#!/usr/bin/env python3\nimport sys\nsys.path.insert(0,{str(source_dir)!r})\nimport reinforcement\nfor line in sys.stdin:\n p=line.rstrip('\\n').split('\\t')\n if p[0]=='new_game': print('new_game\\t'+p[1]+'\\tready',flush=True)\n else: print(p[0]+'\\t'+reinforcement.legal_moves(p[1],p[2])[0],flush=True)\n")
        cli.chmod(0o755)
    else:
        bundled_cli = checkout / "target/release/reversi-ai-cli"
        bundled_cli.parent.mkdir(parents=True)
        shutil.copyfile(cli, bundled_cli)
        bundled_cli.chmod(0o755)
        cli = bundled_cli
    # Fake the compiler invocation, while exercising the actual immutable build receipt path.
    original_run = subprocess.run
    def compiler(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 0) if argv == bundle.BUILD_RECIPE else original_run(argv, **kwargs)
    with patch.object(bundle.subprocess, "run", side_effect=compiler):
        bundle.build_cli(directory / "build", checkout)
    build_receipt = directory / "build/build.json"
    runtime = directory / "oracle-runtime"
    (runtime / "resources").mkdir(parents=True)
    (runtime / "resources/eval.dat").write_text("fixture-resource")
    oracle_binary = runtime / "fake-oracle"
    oracle_binary.write_text(f"#!/usr/bin/env python3\nimport sys\nsys.path.insert(0,{str(checkout / 'tools/reversi-ai-oracle')!r})\nimport oracle\nfrom pathlib import Path\nrows=[]\nfor problem in Path(sys.argv[-1]).read_text().splitlines():\n board=problem[:-1].replace('X','B').replace('O','W').replace('-','.')\n depth=min(board.count('.'),oracle.profile_depth_at(oracle.STRONG_ENGINE_HCAP_V1,63-board.count('.')))\n move=oracle.legal_moves(board,'B')[0]\n rows.append(f'| custom | {{depth}}@100% | {{move}} | +2 | 0:00:00.000 | 1 | 1000 |')\nprint('| '+' | '.join(oracle.HEADER)+' |\\n'+'\\n'.join(rows)+f'\\ntotal {{len(rows)}} nodes in 0s NPS {{len(rows)*1000}}\\n')\n")
    oracle_binary.chmod(0o755)
    stage_paths = {}
    def stage(name, request, previous=()):
        frozen = directory / "manifests" / (name + ".json")
        frozen_bundle.prepare_stage(frozen, name, request, checkout, [stage_paths[p] for p in previous])
        output = directory / "stages" / name
        output.mkdir(parents=True)
        shutil.copyfile(frozen, output / "manifest.json")
        (output / "stdout").write_bytes(b"")
        (output / "stderr").write_bytes(b"")
        with producer("random_inputs", source_dir=source_dir, source_digests=digests) as random:
            frozen_bundle.random_inputs = random
            frozen_bundle.worker_stage(frozen, output / "result.json")
        bundle.save(output / "report.json", {"version": bundle.VERSION, "stage": name,
                    "manifest_sha256": training.sha256_file(frozen), "status": "completed", "exit_code": 0,
                    "wall_seconds": 0.1, "cpu_seconds": 0.01, "peak_observed_rss_bytes": 4096,
                    "sample_seconds": 1, "stdout_sha256": training.sha256_file(output / "stdout"),
                    "stderr_sha256": training.sha256_file(output / "stderr"), "result": bundle.pin(output / "result.json")})
        stage_paths[name] = output / "report.json"
    paths = {}
    for label, seed, counts, prefix, previous in (("calibration", 20260926, {"train": 4,"validation": 2,"held_out": 2}, "calibration-", ()),
                                                   ("full", 20261015, {"train": 2,"validation": 1,"held_out": 1}, "", ("calibration-train",))):
        manifest = directory / label / "manifest.json"
        outputs = directory / label / "generator"
        with producer("random_inputs", source_dir=source_dir, source_digests=digests) as random:
            random.prepare(manifest, seed, counts, 8, 128)
        stage(prefix + "generate", {"generator_manifest": str(manifest), "output_dir": str(outputs), "progress_every": 256}, previous)
        stage(prefix + "verify", {"generator_manifest": str(manifest), "generator_dir": str(outputs), "progress_every": 256}, (prefix + "generate",))
        count = sum(len(training.read_jsonl(outputs / f"{split}.jsonl")) for split in random_inputs.SPLITS)
        artifact, report = directory / label / "baseline/artifact.json", directory / label / "baseline/report.json"
        stage(prefix + "train", {"generator_manifest": str(manifest), "generator_dir": str(outputs), "artifact": str(artifact),
                "report": str(report), "record_total": count, "progress_every": 10000}, (prefix + "verify",))
        paths[label] = (manifest, outputs, artifact, report)
    manifest, outputs, artifact, report = paths["full"]
    corpus_dir, oracle_dir = directory / "corpus", directory / "oracle"
    stage("corpus", {"generator_manifest": str(manifest), "generator_dir": str(outputs), "seed": 99,
          "output_dir": str(corpus_dir), "reservation": unreserved,"progress_every": 256}, ("train",))
    stage("oracle", {"corpus_dir": str(corpus_dir), "binary": str(oracle_binary), "oracle_cwd": str(runtime),
          "output_dir": str(oracle_dir), "progress_every": 12}, ("corpus",))
    probe_dir = directory / "probe"
    stage("cli-probe", {"validation": str(outputs / "validation.jsonl"), "artifact": str(artifact), "cli": str(cli),
          "output_dir": str(probe_dir), "reservation": unreserved}, ("train",))
    completion = {"version": bundle.VERSION, "score_contract": training.SCORE_CONTRACT, "producer": identity,
        "total_wall_budget_seconds": bundle.TOTAL_WALL_SECONDS,
        "generator_manifest": bundle.pin(manifest), "generator_outputs": {p.name: bundle.pin(p) for p in outputs.iterdir()},
        "baseline_artifact": bundle.pin(artifact), "baseline_report": bundle.pin(report),
        "corpus_outputs": {p.name: bundle.pin(p) for p in corpus_dir.iterdir()},
        "oracle_outputs": {str(p.relative_to(oracle_dir)): bundle.pin(p) for p in oracle_dir.rglob("*") if p.is_file()},
        "acceptance_reservation": unreserved, "cli": bundle.cli_identity(cli, identity, build_receipt),
        "cli_probe": bundle.pin(probe_dir / "cli-probe.json"), "stages": {name: bundle.pin(path) for name,path in stage_paths.items()}}
    bundle_path = directory / "bundle.json"
    bundle.save(bundle_path, completion)
    final_manifest = directory / "manifests/bundle-verify.json"
    final_report = directory / "verified-bundle.json"
    frozen_bundle.prepare_stage(final_manifest, "bundle-verify",
                               {"bundle_manifest": str(bundle_path), "cli": str(cli), "report": str(final_report)},
                               checkout, [stage_paths["oracle"], stage_paths["cli-probe"]])
    # The final stage really runs under the process-group wall/RSS supervisor.
    frozen_bundle.supervise(final_manifest, directory / "stages/bundle-verify")
    return bundle_path, completion


class InputBundleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.path, cls.completion = build_small_bundle(Path(cls.temporary.name))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_small_bundle_replays_offline_and_never_qualifies_for_strength(self):
        original = subprocess.Popen
        def only_git(argv, **kwargs):
            if argv[0] != "git":
                raise AssertionError("offline runtime")
            return original(argv, **kwargs)
        with patch.object(bundle.subprocess, "Popen", side_effect=only_git):
            one = bundle.verify_bundle(self.path)
            two = bundle.verify_bundle(self.path)
        self.assertEqual(one, two)
        self.assertFalse(one["strength_inputs"])
        self.assertTrue(one["tooling_only"])
        self.assertEqual(len(one["exposure_keys"]["oracle_root"]), 12)

    def test_full_counts_require_reviewed_oracle_runtime_receipt(self):
        generator = {"counts": dict(random_inputs.COUNTS), "record_start_placements": 8, "max_turns": 128}
        self.assertFalse(bundle.strength_eligible(generator, oracle_runtime_verified=False))
        self.assertTrue(bundle.strength_eligible(generator, oracle_runtime_verified=True))
        generator["counts"] = {"train": 4, "validation": 2, "held_out": 2}
        self.assertFalse(bundle.strength_eligible(generator, oracle_runtime_verified=True))

    def test_pilot_requires_exact_successful_bounded_final_receipt(self):
        receipt = self.path.parent / "stages/bundle-verify/report.json"
        verified = bundle.verify_for_pilot(self.path, receipt)
        self.assertFalse(verified["strength_inputs"])
        self.assertEqual(verified["bundle_verification_receipt"], bundle.pin(receipt))
        with self.assertRaises(training.TrainingError):
            bundle.verify_for_pilot(self.path, receipt.with_name("missing.json"))
        original = receipt.read_bytes()
        try:
            failed = training.read_json(receipt)
            failed["status"] = "wall-limit"
            receipt.write_bytes(bundle.canonical(failed))
            with self.assertRaises(training.TrainingError):
                bundle.verify_for_pilot(self.path, receipt)
            failed["status"] = "completed"
            failed["wall_seconds"] = 2401
            receipt.write_bytes(bundle.canonical(failed))
            with self.assertRaises(training.TrainingError):
                bundle.verify_for_pilot(self.path, receipt)
        finally:
            receipt.write_bytes(original)

    def test_production_cycle_accepts_source_drift_but_keeps_receipt_and_input_pins(self):
        receipt = self.path.parent / "stages/bundle-verify/report.json"
        original_sha256 = training.sha256_file
        active_sources = {(bundle.ROOT / name).resolve() for name in bundle.PRODUCERS}

        def changed_source_hash(path):
            resolved = Path(path).resolve()
            if resolved in active_sources:
                return "0" * 64
            return original_sha256(path)

        with patch.object(training, "sha256_file", side_effect=changed_source_hash):
            with self.assertRaises(training.TrainingError):
                bundle.verify_for_pilot(self.path, receipt)
            with patch.object(bundle, "git", side_effect=AssertionError("producer checkout Git access")):
                verified = bundle.verify_for_production_cycle(self.path, receipt)
        self.assertEqual(verified["bundle_verification_receipt"], bundle.pin(receipt))

        original_receipt = receipt.read_bytes()
        try:
            failed = training.read_json(receipt)
            failed["status"] = "wall-limit"
            receipt.write_bytes(bundle.canonical(failed))
            with self.assertRaises(training.TrainingError):
                bundle.verify_for_production_cycle(self.path, receipt)
        finally:
            receipt.write_bytes(original_receipt)

        pinned_inputs = [
            self.path,
            Path(self.completion["cli"]["binary"]["path"]),
            Path(self.completion["baseline_artifact"]["path"]),
            Path(self.completion["corpus_outputs"]["corpus.jsonl"]["path"]),
            Path(self.completion["oracle_outputs"]["golden.jsonl"]["path"]),
            Path(self.completion["generator_outputs"]["validation.jsonl"]["path"]),
            Path(self.completion["generator_outputs"]["held_out.jsonl"]["path"]),
        ]
        for pinned_path in pinned_inputs:
            with self.subTest(path=pinned_path.name):
                original = pinned_path.read_bytes()
                try:
                    pinned_path.write_bytes(original + (b"\n" if pinned_path == self.path else b"tampered"))
                    with self.assertRaises(training.TrainingError):
                        bundle.verify_for_production_cycle(self.path, receipt)
                finally:
                    pinned_path.write_bytes(original)

    def test_resealed_baseline_report_and_added_verified_flag_rejected(self):
        report = Path(self.completion["baseline_report"]["path"])
        original = report.read_bytes()
        try:
            changed = training.read_json(report)
            changed["report_digest"] = "0" * 64
            report.write_bytes(bundle.canonical(changed))
            completion = dict(self.completion, baseline_report=bundle.pin(report))
            bad = self.path.with_name("bad-baseline.json")
            bundle.save(bad, completion)
            with self.assertRaisesRegex(training.TrainingError, "baseline"):
                bundle.verify_bundle(bad)
        finally:
            report.write_bytes(original)
        bad = self.path.with_name("bad-verified.json")
        bundle.save(bad, dict(self.completion, verified=True))
        with self.assertRaisesRegex(training.TrainingError, "shape"):
            bundle.verify_bundle(bad)

    def test_source_bytes_ancestry_and_cli_match_fail_closed(self):
        identity = json.loads(json.dumps(self.completion["producer"]))
        identity["producer_sources"]["tools/reversi-ai-training/training.py"] = "0" * 64
        with self.assertRaises(training.TrainingError):
            bundle.verify_source(identity)
        with tempfile.TemporaryDirectory() as folder:
            binary = Path(folder) / "binary"
            binary.write_text("different")
            with self.assertRaisesRegex(training.TrainingError, "executable"):
                bundle.verify_bundle(self.path, binary)

    def test_initial_board_is_not_reserved_suite_and_later_collision_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "suite.json"
            board = bundle.reinforcement.INITIAL
            bundle.save(path, {"schema_version": 1, "openings": [{"board": board,"side": "B", "moves": []}]})
            with self.assertRaises(training.TrainingError):
                bundle.reservation({"state":"reserved","artifact":bundle.pin(path),"keys":[training.canonical_position_key(board,"B")]}, path.parent)
        with self.assertRaises(training.TrainingError):
            bundle.check_acceptance_roots(["exposed"], {"train":["exposed"]})

    def test_stage_limits_logs_and_frozen_manifest_reject_reseal(self):
        original = Path(self.completion["stages"]["generate"]["path"])
        report = training.read_json(original)
        report["wall_seconds"] = 601
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)
            for name in ("manifest.json", "stdout", "stderr"):
                shutil.copyfile(original.parent / name, directory / name)
            bundle.save(directory / "report.json", report)
            with self.assertRaises(training.TrainingError):
                bundle.verify_stage(directory / "report.json")


if __name__ == "__main__":
    unittest.main()
