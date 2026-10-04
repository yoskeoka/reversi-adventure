"""Offline checks of gated, durable assessment evidence; no real searches."""

import copy
import contextlib
import io
import hashlib
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import exact_threshold as et
from test_whole_game import synthetic_report, synthetic_game, whole_game as fixture_wg


USAGE = {"user_cpu_ns": 1, "system_cpu_ns": 0, "peak_rss_kib": 100,
         "startup_ns": 1, "shutdown_ns": 1}


def root_source():
    # Vary only the deterministic legal choice. Include games with an early
    # forced pass, which are needed for White to have a 24-empty decision.
    source = synthetic_report(8)
    original = fixture_wg.oracle.legal_moves
    candidates = {"B": source["games"][:2], "W": []}
    for seed in range(20):
        def shuffled(board, side):
            moves = original(board, side)
            if not moves:
                return moves
            offset = int(hashlib.sha256(f"{seed}:{board}:{side}".encode()).hexdigest(), 16) % len(moves)
            return moves[offset:] + moves[:offset]
        row = fixture_wg.opening_rows()[3]
        with patch.object(fixture_wg.oracle, "legal_moves", side_effect=shuffled):
            game = synthetic_game(row, len(candidates["W"]), 8, target_prefix=True)
        root = next((s for s in game["steps"] if s["board"].count(".") == 24 and original(s["board"], s["side"])), None)
        if root and len(candidates[root["side"]]) < 2:
            candidates[root["side"]].append(game)
        if all(len(rows) == 2 for rows in candidates.values()):
            break
    games = candidates["B"] + candidates["W"]
    assert len(games) == 4, "deterministic source must provide both color quotas"
    # Keep every existing opening/assignment identity while applying each
    # selected legal trajectory to its matching row.
    for game in games:
        index = next(i for i, old in enumerate(source["games"]) if (old["opening_id"], old["assignment"]) == (game["opening_id"], game["assignment"]))
        source["games"][index] = game
    source["aggregate"] = fixture_wg.totals(source["games"])
    return et.wg.sealed(source)


SOURCE = root_source()


def no_white_source():
    source = synthetic_report(8)
    original = fixture_wg.oracle.legal_moves
    for index, game in enumerate(source["games"]):
        if not any(s["side"] == "W" and s["board"].count(".") == 24 and original(s["board"], s["side"]) for s in game["steps"]):
            continue
        row = next(r for r in fixture_wg.opening_rows() if r["id"] == game["opening_id"])
        for seed in range(30):
            def shuffled(board, side):
                moves = original(board, side)
                if not moves:
                    return moves
                offset = int(hashlib.sha256(f"{seed}:{board}:{side}".encode()).hexdigest(), 16) % len(moves)
                return moves[offset:] + moves[:offset]
            with patch.object(fixture_wg.oracle, "legal_moves", side_effect=shuffled):
                replacement = synthetic_game(row, game["assignment"], 8)
            if not any(s["side"] == "W" and s["board"].count(".") == 24 and original(s["board"], s["side"]) for s in replacement["steps"]):
                source["games"][index] = replacement
                break
        else:
            raise AssertionError("no-white fixture seed missing")
    source["aggregate"] = fixture_wg.totals(source["games"])
    source = et.wg.sealed(source)
    et.wg.verify(source)
    return source


def fake_oracle_solve(replies=None):
    pending = iter(replies) if replies is not None else None
    def solve(queries, binary, cwd, profile, timeout, *, child_query, runner):
        raw = dict(next(pending) if pending else {"value": 0, "exact": True, "completed_depth": 24})
        board, side = queries[0]
        raw.update(move=et.wg.oracle.legal_moves(board, side)[0], nodes=1, elapsed_ms=1, nps=1000)
        output = "\n".join(["| Level | Depth | Move | Score | Time | Nodes | NPS |",
            f"| custom | {raw['completed_depth']}@100% | {raw['move']} | {raw['value']:+d} | 000:00:00.001 | 1 | 1000 |",
            "total 1 nodes in 0.001s NPS 1000"])
        runner(et.wg.oracle.oracle_argv(binary, profile, solve_path=Path("/fake/problems"), child_query=child_query),
               cwd=cwd, timeout=timeout, fake_stdout=output)
        return [raw]
    return solve


def fake_measured(argv, *, cwd, timeout, observations, fake_stdout):
    observations.append({"argv": list(argv), "wall_ns": 1000, "last_observation": dict(USAGE),
                         "resources": {k: USAGE[k] for k in ("user_cpu_ns", "system_cpu_ns", "peak_rss_kib")},
                         "stdout": fake_stdout, "stderr": ""})
    return subprocess.CompletedProcess(argv, 0, fake_stdout, "")


class FakeSeat:
    failure = None
    calls = 0

    def __init__(self, _kind, _binary, _artifact, depth, _timeout, label, **settings):
        self.depth, self.settings = depth, settings
        self.diagnostics = {}
        self.process = SimpleNamespace(pid=123)

    def new_game(self, identifier):
        return {"game_id": identifier, "acknowledged": True, "protocol": "new_game-v1"}

    def choose(self, identifier, board, side):
        FakeSeat.calls += 1
        if FakeSeat.failure:
            raise FakeSeat.failure
        legal = et.wg.oracle.legal_moves(board, side)
        move = legal[0] if legal else "pass"
        empty = board.count(".")
        exact = empty <= self.settings["exact_empty"]
        occupied = 64 - empty
        depth = empty if exact else 0 if not legal else 12 if occupied <= 20 or occupied >= 45 else self.depth
        self.diagnostics[identifier] = {"elapsed_us": 1, "nodes": 1 if legal or exact else 0,
            "exact": exact, "score": 0 if legal or exact else None, "completed_depth": depth,
            "outcome": "move" if legal else "pass", "cache_probes": 0, "cache_hits": 0, "cache_stores": 0}
        return move, 1

    def collect_diagnostics(self):
        pass

    def close(self):
        return dict(USAGE)

    def abort(self):
        return dict(USAGE)


class ExactThresholdTests(unittest.TestCase):
    def setUp(self):
        self.roots = et.freeze_roots(SOURCE)
        self.manifest = {"report_digest": "manifest-one", "inputs": {
            "cli": {"path": "/fake/cli"}, "artifact": {"path": "/fake/artifact"},
            "oracle": {"path": "/fake/oracle", "sha256": "1"*64}}, "oracle_cwd": "/fake"}
        FakeSeat.failure, FakeSeat.calls = None, 0
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.object(et.wg, "Seat", FakeSeat))
        self.stack.enter_context(patch.object(et.wg, "proc_usage", return_value=dict(USAGE)))
        self.stack.enter_context(contextlib.redirect_stderr(io.StringIO()))

    def measured(self, unit):
        result = et.measure_unit(self.manifest, unit)
        et.verify_unit(self.manifest, unit, result)
        return result

    def pilots(self):
        return [self.measured(unit) for unit in et.units("pilot", self.roots, (24,))]

    def receipts(self, results):
        with patch.object(et.wg.oracle, "run_solve", side_effect=fake_oracle_solve()), \
             patch.object(et, "measured_oracle", side_effect=fake_measured):
            rows = [et.solve_position(self.manifest, job) for job in et.oracle_jobs(results)]
        for row in rows:
            et.verify_position(self.manifest, row["job"], row)
        return rows

    def test_freeze_deterministic_distinct_two_per_color_and_source_identity(self):
        source = copy.deepcopy(SOURCE)
        self.assertEqual(et.freeze_roots(source), self.roots)
        self.assertEqual([r["side"] for r in self.roots].count("B"), 2)
        self.assertEqual([r["side"] for r in self.roots].count("W"), 2)
        self.assertEqual(len({(r["board"], r["side"]) for r in self.roots}), 4)
        expected = []
        seen, counts = set(), {"B": 0, "W": 0}
        for game in source["games"]:
            for step in game["steps"]:
                key = step["board"], step["side"]
                if key[0].count(".") == 24 and et.wg.oracle.legal_moves(*key) and key not in seen and counts[key[1]] < 2:
                    expected.append(step["id"])
                    seen.add(key)
                    counts[key[1]] += 1
        self.assertEqual([r["source_step_id"] for r in self.roots], expected)
        source["settings"]["exact_cache_scope"] = "turn"
        source = et.wg.sealed(source)
        with self.assertRaises(et.wg.BenchmarkError):
            et.freeze_roots(source)

    def test_one_white_root_symmetry_fallback_replays_complete_history(self):
        source = synthetic_report(8, target_prefix=True)
        et.wg.verify(source)
        white_keys = {(s["board"], s["side"]) for game in source["games"] for s in game["steps"]
                      if s["side"] == "W" and s["board"].count(".") == 24
                      and et.wg.oracle.legal_moves(s["board"], s["side"])}
        self.assertEqual(len(white_keys), 1)
        roots = et.freeze_roots(source)
        self.assertEqual(roots, et.freeze_roots(copy.deepcopy(source)))
        self.assertEqual(len(roots), 4)
        self.assertEqual([r["side"] for r in roots].count("B"), 2)
        self.assertEqual([r["side"] for r in roots].count("W"), 2)
        self.assertEqual(len({(r["board"], r["side"]) for r in roots}), 4)
        for root in roots:
            board, side = str(et.wg.oracle.generate_corpus()[0]["board"]), "B"
            for offset in range(0, len(root["opening"]), 2):
                move = root["opening"][offset:offset+2]
                self.assertIn(move, et.wg.oracle.legal_moves(board, side))
                board = et.wg.oracle.apply_move(board, side, move)
                side = et.wg.oracle.other(side)
            for step in root["prefix"]:
                self.assertEqual((step["board"], step["side"]), (board, side))
                self.assertEqual(step["seat"], side if root["assignment"] == 0 else et.wg.oracle.other(side))
                legal = et.wg.oracle.legal_moves(board, side)
                if step["move"] == "pass":
                    self.assertEqual(legal, [])
                    self.assertTrue(et.wg.oracle.legal_moves(board, et.wg.oracle.other(side)))
                else:
                    self.assertIn(step["move"], legal)
                    board = et.wg.oracle.apply_move(board, side, step["move"])
                side = et.wg.oracle.other(side)
            self.assertEqual((board, side), (root["board"], root["side"]))
            self.assertEqual(board.count("."), 24)
            self.assertTrue(et.wg.oracle.legal_moves(board, side))
        generated = [r for r in roots if r["side"] == "W" and (r["board"], r["side"]) not in white_keys]
        self.assertEqual(len(generated), 1)
        self.assertTrue(generated[0].get("source_root_id"))
        self.assertIn((generated[0]["source_board"], "W"), white_keys)
        self.assertEqual(generated[0]["transform"], "rotate-180")
        transformed = generated[0]
        self.assertEqual(transformed["board"], transformed["source_board"][::-1])
        def rotated(move):
            return move if move == "pass" else chr(ord("h") - (ord(move[0]) - ord("a"))) + str(9-int(move[1]))
        original_opening = transformed["source_opening"]
        self.assertEqual(transformed["opening"], "".join(rotated(original_opening[i:i+2]) for i in range(0, len(original_opening), 2)))
        self.assertEqual(transformed["prefix"], [
            {**step, "board": step["board"][::-1], "move": rotated(step["move"])}
            for step in transformed["source_prefix"]])

    def test_units_and_manifest_threshold_identities(self):
        pilots = et.units("pilot", self.roots)
        self.assertEqual(len(pilots), 24)
        self.assertEqual(len({u["id"] for u in pilots}), 24)
        self.assertEqual(len(et.units("full", self.roots)), 96)
        self.assertEqual(len(et.units("full", self.roots, (20,))), 32)
        unit = pilots[0]
        result = self.measured(unit)
        changed = copy.deepcopy(self.manifest)
        changed["report_digest"] = "other-binary-manifest"
        with self.assertRaisesRegex(et.wg.BenchmarkError, "identity"):
            et.verify_unit(changed, unit, result)
        altered = copy.deepcopy(unit)
        altered["threshold"] = 24
        with self.assertRaisesRegex(et.wg.BenchmarkError, "identity"):
            et.verify_unit(self.manifest, altered, result)

    def test_manifest_rejects_resealed_caps_roots_and_unit_registry_changes(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            source_path, manifest_path = directory/"source.json", directory/"manifest.json"
            et.wg.atomic_write(source_path, SOURCE)
            manifest = et.wg.sealed({"version": et.VERSION, "host": "test-host",
                "harness_revision": "test-revision", "caps": dict(et.CAPS),
                "harness_files": [{"path": str(p.resolve())} for p in et.harness_paths()],
                "inputs": {"source_report": {"path": str(source_path)},
                           "openings": {"path": str(et.wg.OPENINGS.resolve())}},
                "roots": self.roots, "source_report_digest": SOURCE["report_digest"],
                "pilot_units": et.units("pilot", self.roots), "pilot_total": 24,
                "cache_lifetime": "one-game", "reset_protocol": "new_game-v1"})
            with patch.object(et.prep, "host", return_value="test-host"), \
                 patch.object(et.prep, "revision", return_value="test-revision"), \
                 patch.object(et.prep, "check_pin"):
                et.wg.atomic_write(manifest_path, manifest)
                self.assertEqual(et.verify_manifest(manifest_path), manifest)
                for field in ("caps", "roots", "pilot_units", "host", "source_report_digest"):
                    changed = copy.deepcopy(manifest)
                    if field == "caps":
                        changed[field]["pilot_node_limit"] += 1
                    elif field == "roots":
                        changed[field][0]["assignment"] ^= 1
                    elif field == "pilot_units":
                        changed[field][0]["threshold"] = 24
                    else:
                        changed[field] = "changed"
                    et.wg.atomic_write(manifest_path, et.wg.sealed(changed))
                    with self.subTest(field=field), self.assertRaises(et.wg.BenchmarkError):
                        et.verify_manifest(manifest_path)

    def prepare_args(self, directory, source):
        cli, oracle, artifact = directory/"fake cli", directory/"fake oracle", directory/"weights.json"
        for path in (cli, oracle):
            path.write_text("#!/usr/bin/env bash\nexit 0\n")
            path.chmod(0o755)
        artifact.write_text('{"fixture":true}\n')
        source_report = directory/"source game-8.json"
        et.wg.atomic_write(source_report, source)
        return SimpleNamespace(cli_binary=cli, oracle_binary=oracle, artifact=artifact,
            source_report=source_report, output_dir=directory/"assessment output",
            source_revision="a"*40, harness_revision=et.prep.revision(), oracle_cwd=directory)

    def test_prepare_pins_real_inputs_and_generates_syntax_valid_one_line_script(self):
        run = subprocess.run
        def cat_file_only(argv, **kwargs):
            if argv[:1] == ["git"] and "cat-file" in argv:
                self.assertEqual(argv[-1], "a"*40+"^{commit}")
                return subprocess.CompletedProcess(argv, 0)
            return run(argv, **kwargs)
        with TemporaryDirectory() as temp:
            args = self.prepare_args(Path(temp), SOURCE)
            output = io.StringIO()
            with patch.object(et.prep, "probe_reset") as probe, \
                 patch.object(et.subprocess, "run", side_effect=cat_file_only), \
                 contextlib.redirect_stdout(output):
                manifest_path = et.prepare(args)
            probe.assert_called_once_with(args.cli_binary, args.artifact, et.CAPS["timeout_seconds"])
            manifest = et.verify_manifest(manifest_path)
            self.assertEqual(manifest["source_revision"], args.source_revision)
            self.assertEqual(manifest["harness_revision"], args.harness_revision)
            self.assertEqual(manifest["source_report_digest"], SOURCE["report_digest"])
            self.assertEqual(manifest["caps"], et.CAPS)
            self.assertEqual(manifest["roots"], self.roots)
            self.assertEqual(manifest["pilot_total"], 24)
            self.assertEqual(manifest["pilot_units"], et.units("pilot", self.roots))
            self.assertEqual(set(manifest["inputs"]), {"cli", "oracle", "artifact", "openings", "source_report"})
            for pin in [*manifest["inputs"].values(), *manifest["harness_files"]]:
                self.assertEqual(et.prep.check_pin(pin), Path(pin["path"]))
            script = args.output_dir/"run-exact-threshold.sh"
            self.assertTrue(script.stat().st_mode & 0o111)
            text = script.read_text()
            self.assertIn("rtk python3", text)
            self.assertIn("--manifest", text)
            self.assertIn('"$@"', text)
            self.assertIn(str(manifest_path), text)
            run(["bash", "-n", str(script)], check=True, capture_output=True)
            self.assertIn("rtk bash", output.getvalue())
            self.assertFalse((args.output_dir/"pilot").exists())
            args.artifact.write_text("changed weights\n")
            with self.assertRaisesRegex(et.wg.BenchmarkError, "input digest"):
                et.verify_manifest(manifest_path)

    def test_prepare_insufficient_color_quota_publishes_no_manifest_or_script(self):
        run = subprocess.run
        def cat_file_only(argv, **kwargs):
            if argv[:1] == ["git"] and "cat-file" in argv:
                return subprocess.CompletedProcess(argv, 0)
            return run(argv, **kwargs)
        with TemporaryDirectory() as temp:
            args = self.prepare_args(Path(temp), no_white_source())
            with patch.object(et.subprocess, "run", side_effect=cat_file_only), \
                 patch.object(et.prep, "probe_reset") as probe, \
                 self.assertRaisesRegex(et.wg.BenchmarkError, "two distinct legal roots per color"):
                et.prepare(args)
            probe.assert_not_called()
            self.assertFalse(args.output_dir.exists())

    def test_transformed_white_manifest_rejects_resealed_history_changes(self):
        run = subprocess.run
        def cat_file_only(argv, **kwargs):
            if argv[:1] == ["git"] and "cat-file" in argv:
                return subprocess.CompletedProcess(argv, 0)
            return run(argv, **kwargs)
        source = synthetic_report(8, target_prefix=True)
        original_white = {(s["board"], s["side"]) for g in source["games"] for s in g["steps"]
                          if s["side"] == "W" and s["board"].count(".") == 24}
        with TemporaryDirectory() as temp:
            args = self.prepare_args(Path(temp), source)
            with patch.object(et.subprocess, "run", side_effect=cat_file_only), \
                 patch.object(et.prep, "probe_reset"), contextlib.redirect_stdout(io.StringIO()):
                path = et.prepare(args)
            manifest = et.verify_manifest(path)
            index = next(i for i, r in enumerate(manifest["roots"]) if r["side"] == "W" and (r["board"], r["side"]) not in original_white)
            for mutation in ("opening", "prefix-board", "prefix-move", "transform", "source-root"):
                changed = copy.deepcopy(manifest)
                root = changed["roots"][index]
                if mutation == "opening":
                    root["opening"] = "a1" + root["opening"][2:]
                elif mutation == "prefix-board":
                    root["prefix"][0]["board"] = "."*64
                elif mutation == "prefix-move":
                    root["prefix"][0]["move"] = "a1"
                elif mutation == "transform":
                    root["transform"] = "main-diagonal"
                else:
                    root["source_board"] = "."*64
                # Also regenerate units so rejection requires the frozen
                # transformed history, rather than a stale unit registry.
                changed["pilot_units"] = et.units("pilot", changed["roots"])
                et.wg.atomic_write(path, et.wg.sealed(changed))
                with self.subTest(mutation=mutation), self.assertRaises(et.wg.BenchmarkError):
                    et.verify_manifest(path)

    def migration_fixture(self, directory):
        args = self.prepare_args(directory, SOURCE)
        run = subprocess.run
        def cat_file_only(argv, **kwargs):
            if argv[:1] == ["git"] and "cat-file" in argv:
                return subprocess.CompletedProcess(argv, 0)
            return run(argv, **kwargs)
        self.stack.enter_context(patch.object(et.subprocess, "run", side_effect=cat_file_only))
        self.stack.enter_context(patch.object(et.prep, "probe_reset"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        old_path = et.prepare(args)
        old = et.prep.load(old_path)
        # Pin the actual committed predecessor harness, rather than pretending
        # the current uncommitted fix was the historical producer.
        for item in old["harness_files"]:
            relative = Path(item["path"]).relative_to(et.prep.ROOT)
            committed = subprocess.check_output(["git", "-C", str(et.prep.ROOT), "show", f"{old['harness_revision']}:{relative}"])
            item["sha256"] = hashlib.sha256(committed).hexdigest()
        old = et.wg.sealed(old)
        et.wg.atomic_write(old_path, old)
        unit = old["pilot_units"][0]
        result = et.measure_unit(old, unit)
        et.verify_unit(old, unit, result)
        source_unit_path = et.unit_path(args.output_dir/"pilot", unit)
        et.wg.atomic_write(source_unit_path, result)
        new_args = copy.copy(args)
        new_args.output_dir = directory/"migration output"
        new_args.resume_manifest = old_path
        return new_args, old_path, source_unit_path, result

    def test_resume_prepare_preserves_source_provenance_and_skips_imported_unit(self):
        with TemporaryDirectory() as temp:
            args, old_path, source_unit_path, original = self.migration_fixture(Path(temp))
            snapshots = old_path.read_bytes(), source_unit_path.read_bytes()
            new_path = et.prepare(args)
            manifest = et.verify_manifest(new_path)
            imported = et.resume_sources(manifest)
            self.assertEqual(len(imported), 1)
            saved = et.prep.load(et.unit_path(args.output_dir/"pilot", original["unit"]))
            self.assertEqual(saved, imported[0])
            self.assertEqual(saved["manifest_digest"], manifest["report_digest"])
            self.assertNotEqual(saved["manifest_digest"], original["manifest_digest"])
            self.assertEqual(saved["steps"], original["steps"])
            self.assertEqual(saved["seat_processes"], original["seat_processes"])
            self.assertEqual(saved["imported_from"], {"manifest": et.prep.pin(old_path),
                "unit": et.prep.pin(source_unit_path), "report_digest": original["report_digest"]})
            self.assertEqual((old_path.read_bytes(), source_unit_path.read_bytes()), snapshots)
            with patch.object(et.wg, "Seat", side_effect=AssertionError("imported unit must skip")):
                self.assertEqual(et.run_units(manifest, [original["unit"]], args.output_dir/"pilot", et.Progress()), [saved])

    def test_resume_rejects_changed_source_pins_and_workload_identity(self):
        with TemporaryDirectory() as temp:
            args, old_path, source_unit_path, _ = self.migration_fixture(Path(temp))
            new_path = et.prepare(args)
            manifest = et.prep.load(new_path)
            for field in ("source_revision", "inputs", "caps", "source_report_digest"):
                changed = copy.deepcopy(manifest)
                if field == "inputs":
                    changed[field]["artifact"]["sha256"] = "f"*64
                elif field == "caps":
                    changed[field]["pilot_node_limit"] += 1
                else:
                    changed[field] = "b"*40
                with self.subTest(field=field), self.assertRaisesRegex(et.wg.BenchmarkError, "resume source"):
                    et.resume_sources(et.wg.sealed(changed))
            for source_path in (old_path, source_unit_path):
                raw = source_path.read_bytes()
                source_path.write_bytes(raw+b" ")
                with self.subTest(path=source_path.name), self.assertRaisesRegex(et.wg.BenchmarkError, "input digest"):
                    et.resume_sources(manifest)
                source_path.write_bytes(raw)

    def test_resume_prepare_mismatch_publishes_nothing_and_historical_harness_verified(self):
        with TemporaryDirectory() as temp:
            args, old_path, _, _ = self.migration_fixture(Path(temp))
            args.source_revision = "b"*40
            with self.assertRaisesRegex(et.wg.BenchmarkError, "source_revision mismatch"):
                et.prepare(args)
            self.assertFalse(args.output_dir.exists())
            args.source_revision = "a"*40
            old = et.prep.load(old_path)
            old["harness_files"][0]["sha256"] = "f"*64
            et.wg.atomic_write(old_path, et.wg.sealed(old))
            with self.assertRaisesRegex(et.wg.BenchmarkError, "harness differs from recorded commit"):
                et.prepare(args)
            self.assertFalse(args.output_dir.exists())

    def test_removed_import_provenance_resealed_checkpoint_rejected_before_launch(self):
        with TemporaryDirectory() as temp:
            args, _, _, original = self.migration_fixture(Path(temp))
            path = et.prepare(args)
            manifest = et.verify_manifest(path)
            unit = original["unit"]
            checkpoint = et.unit_path(args.output_dir/"pilot", unit)
            changed = et.prep.load(checkpoint)
            changed.pop("imported_from")
            et.wg.atomic_write(checkpoint, et.wg.sealed(changed))
            with patch.object(et.wg, "Seat", side_effect=AssertionError("tampered import must not launch")), \
                 patch.object(et, "measure_unit", side_effect=AssertionError("tampered import must not measure")):
                with self.assertRaises(et.wg.BenchmarkError):
                    et.preflight(manifest, args.output_dir)
                with self.assertRaises(et.wg.BenchmarkError):
                    et.run_units(manifest, [unit], args.output_dir/"pilot", et.Progress())

    def test_legacy_failed_unit_wait4_only_aggregate_normalized_without_source_edit(self):
        with TemporaryDirectory() as temp:
            args, old_path, source_unit_path, original = self.migration_fixture(Path(temp))
            old_manifest = et.prep.load(old_path)
            FakeSeat.failure = et.wg.BenchmarkError("legacy incomplete decision")
            try:
                with patch.object(et.wg, "proc_usage", return_value=dict(USAGE, peak_rss_kib=250)):
                    failed = et.measure_unit(old_manifest, original["unit"])
            finally:
                FakeSeat.failure = None
            self.assertEqual(failed["status"], "failed")
            self.assertEqual(failed["resources"]["peak_rss_kib"], 250)
            failed["resources"] = et.process_resources(failed["seat_processes"])
            legacy = et.wg.sealed(failed)
            self.assertEqual(legacy["resources"]["peak_rss_kib"], 100)
            et.wg.atomic_write(source_unit_path, legacy)
            snapshots = old_path.read_bytes(), source_unit_path.read_bytes()
            path = et.prepare(args)
            manifest = et.verify_manifest(path)
            imported = et.resume_sources(manifest)[0]
            self.assertEqual(imported["status"], "failed")
            self.assertEqual(imported["failure"], legacy["failure"])
            self.assertEqual(imported["seat_processes"], legacy["seat_processes"])
            self.assertEqual(imported["failed_attempt"], legacy["failed_attempt"])
            self.assertEqual(imported["resources"]["peak_rss_kib"], 250)
            self.assertEqual(imported["imported_from"]["report_digest"], legacy["report_digest"])
            self.assertEqual((old_path.read_bytes(), source_unit_path.read_bytes()), snapshots)
            with patch.object(et.wg, "Seat", side_effect=AssertionError("imported failure must skip")):
                self.assertEqual(et.run_units(manifest, [original["unit"]], args.output_dir/"pilot", et.Progress()), [imported])

    def test_pass_window_preserves_board_and_completes(self):
        record = next(r for r in et.wg.oracle.generate_corpus() if r["outcome"]["kind"] == "Pass" and r["board"].count(".") > 12)
        unit = copy.deepcopy(et.units("pilot", self.roots, (24,))[0])
        unit["start"].update(board=record["board"], side=record["side_to_move"])
        result = self.measured(unit)
        self.assertEqual(result["steps"][0]["move"], "pass")
        self.assertEqual(result["steps"][0]["board"], result["steps"][1]["board"])
        self.assertNotEqual(result["steps"][0]["side"], result["steps"][1]["side"])
        self.assertTrue(et.reached(unit, result["end_board"], result["end_side"]))

    def test_failure_saved_and_skipped_without_launch(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        FakeSeat.failure = et.wg.BenchmarkError("decision node limit exhausted")
        with TemporaryDirectory() as temp:
            directory = Path(temp)/"pilot"
            rows = et.run_units(self.manifest, [unit], directory, et.Progress())
            self.assertEqual(rows[0]["status"], "failed")
            self.assertIn("node limit", rows[0]["failure"])
            self.assertIsNotNone(rows[0]["failed_attempt"])
            with patch.object(et.wg, "Seat", side_effect=AssertionError("must skip saved failure")):
                self.assertEqual(et.run_units(self.manifest, [unit], directory, et.Progress()), rows)

    def test_corrupt_unit_is_rejected_before_launch(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        result = self.measured(unit)
        for mutation in ("digest", "resources", "move", "threshold"):
            changed = copy.deepcopy(result)
            if mutation == "digest":
                changed["wall_ns"] += 1
            elif mutation == "resources":
                changed["resources"]["user_cpu_ns"] += 1
            elif mutation == "move":
                changed["steps"][0]["move"] = "z9"
            else:
                changed["unit"]["threshold"] = 20
            if mutation != "digest":
                changed = et.wg.sealed(changed)
            with self.subTest(mutation=mutation), TemporaryDirectory() as temp:
                directory = Path(temp)
                et.wg.atomic_write(et.unit_path(directory, unit), changed)
                with patch.object(et.wg, "Seat", side_effect=AssertionError("must reject before launch")), self.assertRaises(et.wg.BenchmarkError):
                    et.run_units(self.manifest, [unit], directory, et.Progress())

    def test_sampled_rss_above_wait4_is_preserved_and_verified(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        sampled = dict(USAGE, peak_rss_kib=200)
        with patch.object(et.wg, "proc_usage", return_value=sampled):
            result = self.measured(unit)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["resources"]["peak_rss_kib"], 200)
        self.assertEqual(result["seat_processes"]["B"]["peak_rss_kib"], 100)
        self.assertEqual(result["seat_processes"]["W"]["peak_rss_kib"], 100)
        self.assertTrue(all(s["cpu_after"]["peak_rss_kib"] == s["process_peak_rss_kib"] == 200 for s in result["steps"]))
        corrupted = copy.deepcopy(result)
        corrupted["resources"]["peak_rss_kib"] = 100
        corrupted = et.wg.sealed(corrupted)
        with self.assertRaisesRegex(et.wg.BenchmarkError, "aggregate"):
            et.verify_unit(self.manifest, unit, corrupted)

    def test_wait4_rss_above_samples_is_preserved_and_verified(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        waited = dict(USAGE, peak_rss_kib=200)
        with patch.object(FakeSeat, "close", return_value=waited), \
             patch.object(FakeSeat, "abort", return_value=waited):
            result = self.measured(unit)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["resources"]["peak_rss_kib"], 200)
        self.assertEqual(result["seat_processes"]["B"]["peak_rss_kib"], 200)
        self.assertTrue(all(s["process_peak_rss_kib"] == 100 for s in result["steps"]))

    def test_sampled_rss_before_above_after_uses_both_raw_observations(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        calls = 0
        def observed(_pid):
            nonlocal calls
            calls += 1
            return dict(USAGE, peak_rss_kib=250 if calls % 2 else 200)
        with patch.object(et.wg, "proc_usage", side_effect=observed):
            result = self.measured(unit)
        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["resources"]["peak_rss_kib"], 250)
        self.assertTrue(all(s["cpu_before"]["peak_rss_kib"] == 250 and s["cpu_after"]["peak_rss_kib"] == 200 for s in result["steps"]))
        corrupted = copy.deepcopy(result)
        corrupted["resources"]["peak_rss_kib"] = 200
        with self.assertRaisesRegex(et.wg.BenchmarkError, "aggregate"):
            et.verify_unit(self.manifest, unit, et.wg.sealed(corrupted))

    def test_mid_decision_peak_above_endpoints_and_wait4_is_in_aggregate_and_cap(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        wait4 = dict(USAGE, peak_rss_kib=80)
        with patch.object(FakeSeat, "close", return_value=wait4), \
             patch.object(FakeSeat, "abort", return_value=wait4):
            result = self.measured(unit)
        step = result["steps"][0]
        step["cpu_after"] = dict(step["cpu_after"], peak_rss_kib=200)
        step["process_peak_rss_kib"] = 200
        step["peak_observation"] = {"user_cpu_ns": 1, "system_cpu_ns": 0, "peak_rss_kib": 900}
        result["resources"]["peak_rss_kib"] = 900
        result = et.wg.sealed(result)
        self.assertEqual(et.process_resources(result["seat_processes"], result["steps"])["peak_rss_kib"], 900)
        et.verify_unit(self.manifest, unit, result)
        self.assertEqual(result["seat_processes"]["B"]["peak_rss_kib"], 80)
        self.assertEqual(result["steps"][0]["cpu_before"]["peak_rss_kib"], 100)
        self.assertEqual(result["steps"][0]["cpu_after"]["peak_rss_kib"], 200)
        for corruption in ("under-aggregate", "over-cap"):
            changed = copy.deepcopy(result)
            if corruption == "under-aggregate":
                changed["resources"]["peak_rss_kib"] = 200
            else:
                peak = et.CAPS["max_rss_kib"]+1
                changed["steps"][0]["peak_observation"]["peak_rss_kib"] = peak
                changed["resources"]["peak_rss_kib"] = peak
            with self.subTest(corruption=corruption), self.assertRaises(et.wg.BenchmarkError):
                et.verify_unit(self.manifest, unit, et.wg.sealed(changed))

    def test_failed_attempt_mid_decision_peak_preserved_in_aggregate(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        wait4 = dict(USAGE, peak_rss_kib=80)
        FakeSeat.failure = et.wg.BenchmarkError("fixture incomplete decision")
        try:
            with patch.object(FakeSeat, "abort", return_value=wait4):
                result = self.measured(unit)
        finally:
            FakeSeat.failure = None
        self.assertEqual(result["status"], "failed")
        result["failed_attempt"]["peak_observation"] = {"user_cpu_ns": 1, "system_cpu_ns": 0, "peak_rss_kib": 900}
        result["resources"]["peak_rss_kib"] = 900
        result = et.wg.sealed(result)
        self.assertEqual(et.process_resources(result["seat_processes"], result["steps"], result["failed_attempt"])["peak_rss_kib"], 900)
        et.verify_unit(self.manifest, unit, result)
        self.assertEqual(result["failed_attempt"]["before_usage"]["peak_rss_kib"], 100)
        self.assertEqual(result["seat_processes"]["B"]["peak_rss_kib"], 80)
        changed = copy.deepcopy(result)
        changed["resources"]["peak_rss_kib"] = 100
        with self.assertRaisesRegex(et.wg.BenchmarkError, "aggregate"):
            et.verify_unit(self.manifest, unit, et.wg.sealed(changed))

    def test_rss_cap_enforced_on_both_raw_sources_and_failures_reverify(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        over = dict(USAGE, peak_rss_kib=et.CAPS["max_rss_kib"]+1)
        for source in ("proc-before", "proc-after", "wait4"):
            with self.subTest(source=source), contextlib.ExitStack() as patches:
                if source.startswith("proc"):
                    observations = iter([over, dict(USAGE)] if source == "proc-before" else [dict(USAGE), over])
                    patches.enter_context(patch.object(et.wg, "proc_usage", side_effect=lambda _pid: next(observations)))
                else:
                    patches.enter_context(patch.object(FakeSeat, "close", return_value=over))
                    patches.enter_context(patch.object(FakeSeat, "abort", return_value=over))
                result = self.measured(unit)
                self.assertEqual(result["status"], "failed")
                self.assertIn("RSS", result["failure"])
                self.assertEqual(result["resources"]["peak_rss_kib"], over["peak_rss_kib"])
                if source.startswith("proc"):
                    self.assertIsNotNone(result["failed_attempt"])
                    self.assertEqual(result["seat_processes"]["B"]["peak_rss_kib"], 100)
                else:
                    self.assertTrue(result["steps"])
                    self.assertEqual(result["seat_processes"]["B"]["peak_rss_kib"], over["peak_rss_kib"])

    def test_relaxed_rss_relationship_keeps_wait4_cpu_reconciliation(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        with patch.object(et.wg, "proc_usage", return_value=dict(USAGE, peak_rss_kib=200)):
            result = self.measured(unit)
        changed = copy.deepcopy(result)
        step = changed["steps"][0]
        step["cpu_after"] = dict(step["cpu_after"])
        step["cpu_after"]["user_cpu_ns"] = step["cpu_before"]["user_cpu_ns"]+2
        step["decision_cpu_ns"] = 2
        changed = et.wg.sealed(changed)
        with self.assertRaisesRegex(et.wg.BenchmarkError, "CPU exceeds wait4"):
            et.verify_unit(self.manifest, unit, changed)

    def test_interrupted_unit_not_saved_completed_unit_resumes(self):
        rows = et.units("pilot", self.roots, (24,))[:2]
        first = self.measured(rows[0])
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            with patch.object(et, "measure_unit", side_effect=[first, KeyboardInterrupt]):
                with self.assertRaises(KeyboardInterrupt):
                    et.run_units(self.manifest, rows, directory, et.Progress())
            self.assertTrue(et.unit_path(directory, rows[0]).exists())
            self.assertFalse(et.unit_path(directory, rows[1]).exists())
            second = self.measured(rows[1])
            with patch.object(et, "measure_unit", return_value=second) as measure:
                completed = et.run_units(self.manifest, rows, directory, et.Progress())
            measure.assert_called_once_with(self.manifest, rows[1])
            self.assertEqual(completed, [first, second])

    def test_interrupted_decision_aborts_both_seats_and_is_not_published(self):
        unit = et.units("pilot", self.roots, (24,))[0]
        FakeSeat.failure = KeyboardInterrupt()
        with patch.object(FakeSeat, "abort", return_value=dict(USAGE)) as abort:
            with self.assertRaises(KeyboardInterrupt):
                et.measure_unit(self.manifest, unit)
        self.assertEqual(abort.call_count, 2)

    def test_oracle_root_child_incomplete_and_mismatch_are_durable_failures(self):
        result = self.measured(et.units("pilot", self.roots, (24,))[0])
        job = et.oracle_jobs([result])[0]
        good = {"value": 0, "exact": True, "completed_depth": 24}
        cases = [[dict(good, exact=False)], [good, dict(good, exact=False)],
                 [dict(good, value=1), good], [good, dict(good, value=1)]]
        for replies in cases:
            with self.subTest(replies=replies), patch.object(et.wg.oracle, "run_solve", side_effect=fake_oracle_solve(replies)), \
                 patch.object(et, "measured_oracle", side_effect=fake_measured):
                receipt = et.solve_position(self.manifest, job)
            self.assertEqual(receipt["status"], "failed")
            et.verify_position(self.manifest, job, receipt)
        with TemporaryDirectory() as temp, patch.object(et, "solve_position", return_value=receipt):
            directory = Path(temp)/"oracle"
            with patch.object(et, "oracle_jobs", return_value=[job]):
                saved = et.run_oracle(self.manifest, [result], directory, et.Progress())
                with patch.object(et, "solve_position", side_effect=AssertionError("skip failed Oracle")):
                    self.assertEqual(et.run_oracle(self.manifest, [result], directory, et.Progress()), saved)

    def test_resealed_incomplete_oracle_checkpoint_rejected(self):
        result = self.measured(et.units("pilot", self.roots, (24,))[0])
        receipt = self.receipts([result])[0]
        for index in (0, 1):
            changed = copy.deepcopy(receipt)
            changed["queries"][index]["result"]["completed_depth"] = 1
            changed = et.wg.sealed(changed)
            with self.subTest(index=index), self.assertRaises(et.wg.BenchmarkError):
                et.verify_position(self.manifest, changed["job"], changed)

    def test_oracle_interrupted_position_resumes_without_repeating_saved_solve(self):
        result = self.measured(et.units("pilot", self.roots, (24,))[0])
        receipts = self.receipts([result])[:2]
        jobs = [r["job"] for r in receipts]
        with TemporaryDirectory() as temp, patch.object(et, "oracle_jobs", return_value=jobs):
            directory = Path(temp)/"oracle"
            with patch.object(et, "solve_position", side_effect=[receipts[0], KeyboardInterrupt]):
                with self.assertRaises(KeyboardInterrupt):
                    et.run_oracle(self.manifest, [result], directory, et.Progress())
            self.assertTrue((directory/(jobs[0]["id"]+".json")).exists())
            self.assertFalse((directory/(jobs[1]["id"]+".json")).exists())
            with patch.object(et, "solve_position", return_value=receipts[1]) as solve:
                self.assertEqual(et.run_oracle(self.manifest, [result], directory, et.Progress()), receipts)
            solve.assert_called_once_with(self.manifest, jobs[1])

    def test_measured_oracle_collects_wait4_resources_and_raw_console(self):
        observations = []
        argv = [sys.executable, "-c", "import sys; print('raw solve'); print('diagnostic', file=sys.stderr)"]
        result = et.measured_oracle(argv, cwd=Path("/tmp"), timeout=2, observations=observations)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "raw solve\n")
        self.assertEqual(result.stderr, "diagnostic\n")
        self.assertEqual(len(observations), 1)
        receipt = observations[0]
        self.assertEqual(receipt["argv"], argv)
        self.assertEqual(receipt["stdout"], result.stdout)
        self.assertEqual(receipt["stderr"], result.stderr)
        self.assertGreater(receipt["wall_ns"], 0)
        self.assertGreater(receipt["resources"]["peak_rss_kib"], 0)
        self.assertGreaterEqual(receipt["resources"]["user_cpu_ns"], 0)
        self.assertGreaterEqual(receipt["resources"]["system_cpu_ns"], 0)

    def test_measured_oracle_timeout_and_active_rss_abort_retain_resources(self):
        argv = [sys.executable, "-c", "import time; print('before abort', flush=True); time.sleep(5)"]
        for reason in ("timeout", "RSS"):
            observations = []
            usage = dict(USAGE)
            if reason == "RSS":
                usage["peak_rss_kib"] = et.CAPS["max_rss_kib"] + 1
            with self.subTest(reason=reason), patch.object(et.wg, "proc_usage", return_value=usage), \
                 self.assertRaisesRegex(et.wg.BenchmarkError, reason):
                et.measured_oracle(argv, cwd=Path("/tmp"), timeout=0.05 if reason == "timeout" else 2,
                                   observations=observations)
            self.assertEqual(len(observations), 1)
            self.assertIsNotNone(observations[0]["resources"])
            self.assertGreater(observations[0]["resources"]["peak_rss_kib"], 0)
            self.assertGreater(observations[0]["wall_ns"], 0)
            self.assertLess(observations[0]["wall_ns"], 1_000_000_000)
            self.assertEqual(observations[0]["last_observation"], usage)
            if reason == "timeout":
                # A deadline may precede interpreter startup on a busy host.
                self.assertIn(observations[0]["stdout"], ("", "before abort\n"))

    def test_oracle_completed_checkpoint_requires_matching_raw_process_evidence(self):
        result = self.measured(et.units("pilot", self.roots, (24,))[0])
        receipt = self.receipts([result])[0]
        self.assertEqual(len(receipt["process_observations"]), len(receipt["queries"]))
        for mutation in ("missing", "stdout-score", "rss", "cpu", "argv", "legal-continuation"):
            changed = copy.deepcopy(receipt)
            observation = changed["process_observations"][0]
            if mutation == "missing":
                changed["process_observations"].pop()
            elif mutation == "stdout-score":
                observation["stdout"] = observation["stdout"].replace("| +0 |", "| +1 |")
            elif mutation == "rss":
                observation["resources"]["peak_rss_kib"] = et.CAPS["max_rss_kib"] + 1
            elif mutation == "cpu":
                observation["resources"]["user_cpu_ns"] = -1
            elif mutation == "argv":
                observation["argv"][0] = "/other/oracle"
            else:
                raw = changed["queries"][0]["result"]
                observation["stdout"] = observation["stdout"].replace(f"| {raw['move']} |", "| a1 |")
                raw["move"] = "a1"
                self.assertNotIn("a1", et.wg.oracle.legal_moves(changed["queries"][0]["board"], changed["queries"][0]["effective_side"]))
            changed = et.wg.sealed(changed)
            with self.subTest(mutation=mutation), self.assertRaises((et.wg.BenchmarkError, et.wg.oracle.OracleError)):
                et.verify_position(self.manifest, changed["job"], changed)

    def test_gate_all_four_both_scopes_complete_matching_and_oracle(self):
        pilots = self.pilots()
        receipts = self.receipts(pilots)
        self.assertEqual(et.admitted_thresholds(pilots, receipts)[0], [24])
        for case in ("missing-window", "failed", "mismatch", "missing-oracle", "failed-oracle", "one-scope", "wrong-root", "duplicate-root"):
            results, evidence = copy.deepcopy(pilots), copy.deepcopy(receipts)
            if case == "missing-window":
                results.pop()
            elif case == "failed":
                results[0]["status"] = "failed"
            elif case == "mismatch":
                results[0]["steps"][0]["search"]["score"] = 1
            elif case == "missing-oracle":
                evidence.pop()
            elif case == "failed-oracle":
                evidence[0]["status"] = "failed"
            elif case == "one-scope":
                results = [copy.deepcopy(r) for r in pilots if r["unit"]["scope"] == "game"]*2
                evidence = self.receipts(results)
            elif case == "wrong-root":
                results[0]["unit"]["start"]["assignment"] ^= 1
            else:
                results[1]["unit"]["start"] = copy.deepcopy(results[0]["unit"]["start"])
            with self.subTest(case=case):
                self.assertNotIn(24, et.admitted_thresholds(results, evidence)[0])

    def test_full_partial_failures_never_report_averages(self):
        unit = et.units("full", self.roots, (24,))[0]
        result = self.measured(unit)
        for rows in ([result], [copy.deepcopy(result) for _ in range(16)]):
            if len(rows) == 16:
                rows[-1]["status"] = "failed"
            summary = et.assessment_summary(rows, [], [24], {})
            for condition in summary["conditions"]:
                self.assertEqual(condition["status"], "failed")
                self.assertNotIn("totals", condition)
                self.assertNotIn("wall_ratio", condition)
                self.assertIn("no partial averages", condition["failure"])


if __name__ == "__main__":
    unittest.main()
