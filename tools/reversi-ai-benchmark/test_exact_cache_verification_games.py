"""Synthetic game/resource receipts; never starts a CLI search."""

import copy
import io
import time
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import exact_cache_verification_games as games

USAGE = {"user_cpu_ns": 1, "system_cpu_ns": 0, "peak_rss_kib": 100,
         "startup_ns": 1, "shutdown_ns": 1}


class FakeSeat:
    failure = None
    policy = True
    instances = []

    def __init__(self, _kind, _binary, _artifact, depth, _timeout, label, **settings):
        self.depth, self.settings = depth, settings
        self.diagnostics = {}
        self.process = SimpleNamespace(pid=123)
        self.started_at_ns = time.time_ns()
        self.closed = False
        self.instances.append(self)

    def new_game(self, identifier):
        return {"game_id": identifier, "acknowledged": True, "protocol": "new_game-v1", "elapsed_ns": 1}

    def choose(self, identifier, board, side):
        if self.failure:
            raise self.failure
        legal = games.wg.oracle.legal_moves(board, side)
        move = legal[0] if legal else "pass"
        empty, occupied = board.count("."), 64-board.count(".")
        exact = empty <= self.settings["exact_empty"]
        depth = empty if exact else 0 if not legal else 12 if occupied <= 20 or occupied >= 45 else self.depth
        diagnostic = {"score_contract": "winner-empty-v1", "search_semantics_version": 2,
            "score_identity_raw": f"score_contract_v1\tposition_id={identifier}\tscore_contract=winner-empty-v1\tsearch_semantics_version=2",
            "elapsed_us": 1, "nodes": 1 if legal or exact else 0,
            "exact": exact, "score": 0 if legal or exact else None, "completed_depth": depth,
            "outcome": "move" if legal else "pass", "cache_probes": 0, "cache_hits": 0, "cache_stores": 0}
        if self.policy:
            scope = self.settings["cache_scope"]
            diagnostic["exact_cache_policy"] = {"scope": scope, "policy": games.POLICIES[scope],
                "raw": f"exact_cache_policy_v1\tposition_id={identifier}\texact_cache_scope={scope}"
                       f"\texact_cache_policy={games.POLICIES[scope]}"}
        self.diagnostics[identifier] = diagnostic
        return move, 1

    def collect_diagnostics(self):
        pass

    def usage(self):
        return {**USAGE, "started_at_ns": self.started_at_ns, "ended_at_ns": time.time_ns()}

    def close(self):
        self.closed = True
        return self.usage()

    def abort(self):
        return None if self.closed else self.usage()


class GamesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = {"report_digest": "manifest-fixture", "inputs": {
            "cli": {"path": "/fake/cli"}, "artifact": {"path": "/fake/artifact"}}}
        cls.units = games.units({"games": games.GAME_IDENTITIES})
        with patch.object(games.wg, "Seat", FakeSeat), patch.object(games.wg, "proc_usage", return_value=dict(USAGE)):
            cls.results = [games.measure_unit(cls.manifest, unit) for unit in cls.units]

    def measure(self, unit):
        with patch.object(games.wg, "Seat", FakeSeat), patch.object(games.wg, "proc_usage", return_value=dict(USAGE)):
            return games.measure_unit(self.manifest, unit)

    def test_exact_order_settings_and_identity(self):
        self.assertEqual(len(self.units), 6)
        self.assertEqual([u["scope"] for u in self.units], ["turn"]*3+["game"]*3)
        self.assertEqual([u["start"]["opening_id"] for u in self.units[:3]], ["opening-1", "opening-2", "opening-4"])
        self.assertTrue(all(u["threshold"] == 20 and u["depth"] == 8 and u["start"]["assignment"] == 0 for u in self.units))
        for identities in (games.GAME_IDENTITIES[:2], list(reversed(games.GAME_IDENTITIES)),
                           games.GAME_IDENTITIES*2, [{"opening_id": "opening-1", "assignment": 1}]*3):
            with self.subTest(identities=identities), self.assertRaises(games.wg.BenchmarkError):
                games.units({"games": identities})

    def test_completed_receipts_and_semantics(self):
        for unit, result in zip(self.units, self.results):
            games.verify_unit(self.manifest, unit, result)
        for index in range(3):
            games.semantic_pair(self.results[index], self.results[index+3])
        report = games.summary(self.results)
        self.assertTrue(report["games_matched"])
        self.assertFalse(report["adoption"])
        self.assertTrue(all("averages" in condition for condition in report["conditions"]))

    def test_missing_policy_saved_as_failure_without_retry(self):
        with patch.object(FakeSeat, "policy", False):
            result = self.measure(self.units[0])
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["policy_failures"])
        games.verify_unit(self.manifest, self.units[0], result)
        rows = [result, *self.results[1:]]
        self.assertNotIn("averages", games.summary(rows)["conditions"][0])

    def test_failed_attempt_is_saved_and_verified(self):
        with patch.object(FakeSeat, "failure", games.wg.BenchmarkError("fixture timeout")):
            result = self.measure(self.units[0])
        self.assertEqual(result["status"], "failed")
        self.assertIn("timeout", result["failure"])
        self.assertEqual(result["failed_attempt"]["board"], self.units[0]["start"]["board"])
        games.verify_unit(self.manifest, self.units[0], result)
        changed = copy.deepcopy(result)
        changed["failed_attempt"]["before_usage"]["peak_rss_kib"] = 0
        with self.assertRaises(games.wg.BenchmarkError):
            games.verify_unit(self.manifest, self.units[0], games.wg.sealed(changed))

    def test_keyboard_interrupt_aborts_without_checkpoint(self):
        with patch.object(FakeSeat, "failure", KeyboardInterrupt()), self.assertRaises(KeyboardInterrupt):
            self.measure(self.units[0])

    def test_resealed_bad_evidence_rejected(self):
        mutations = {
            "reset": lambda r: r["reset_events"]["B"].update(acknowledged=False),
            "rss": lambda r: r["steps"][0]["cpu_before"].update(peak_rss_kib=0),
            "missing-process-time": lambda r: r["seat_processes"]["B"].pop("started_at_ns"),
            "lifecycle": lambda r: r.update(ended_at_ns=False),
            "timeout": lambda r: r["steps"][0].update(decision_elapsed_ns=311_000_000_000),
            "policy": lambda r: r["steps"][0]["search"]["exact_cache_policy"].update(scope="game"),
            "policy-raw": lambda r: r["steps"][0]["search"]["exact_cache_policy"].update(raw="forged"),
            "settings": lambda r: r["unit"].update(threshold=16),
            "format": lambda r: r.update(version=games.et.VERSION),
        }
        for label, mutate in mutations.items():
            changed = copy.deepcopy(self.results[0])
            mutate(changed)
            with self.subTest(label=label), self.assertRaises(games.wg.BenchmarkError):
                games.verify_unit(self.manifest, self.units[0], games.wg.sealed(changed))
        with self.assertRaises(games.wg.BenchmarkError):
            games.verify_unit({**self.manifest, "report_digest": "other"}, self.units[0], self.results[0])

    def test_summary_refuses_extra_duplicate_order_and_partial_average(self):
        for rows in (self.results*2, list(reversed(self.results))):
            with self.assertRaises(games.wg.BenchmarkError):
                games.summary(rows)
        report = games.summary(self.results[:2])
        self.assertFalse(report["games_matched"])
        self.assertTrue(all("averages" not in c for c in report["conditions"]))
        changed = copy.deepcopy(self.results)
        changed[3]["steps"][0]["search"]["score"] += 1
        self.assertFalse(games.summary(changed)["games_matched"])
        self.assertEqual(games.summary(changed)["comparisons"][0]["status"], "failed")
        self.assertTrue(all("averages" not in condition for condition in games.summary(changed)["conditions"]))

    def test_policy_capture_keeps_original_diagnostic_fields(self):
        seat = object.__new__(games.wg.Seat)
        seat.stderr = io.StringIO("exact_cache_policy_v1\tposition_id=p\texact_cache_scope=turn"
            "\texact_cache_policy=exact-cache-cross-decision-suspended-v1\n"
            "search_diagnostic_v1\tposition_id=p\telapsed_us=1\tnodes=1\texact=false\tscore=0"
            "\tcompleted_depth=8\toutcome=move\tcache_probes=0\tcache_hits=0\tcache_stores=0\n")
        seat.diagnostic_offset, seat.diagnostics, seat.cache_policies = 0, {}, {}
        seat.score_identities = {}
        seat.capture_cache_policy = True
        seat.collect_diagnostics()
        self.assertEqual(seat.diagnostics["p"]["exact_cache_policy"]["scope"], "turn")
        self.assertEqual(seat.diagnostics["p"]["completed_depth"], 8)
        seat.collect_diagnostics()

    def test_legacy_diagnostics_ignore_cache_policy_by_default(self):
        seat = object.__new__(games.wg.Seat)
        seat.stderr = io.StringIO("exact_cache_policy_v1\tposition_id=p\texact_cache_scope=turn"
            "\texact_cache_policy=exact-cache-cross-decision-suspended-v1\n"
            "search_diagnostic_v1\tposition_id=p\telapsed_us=1\tnodes=1\texact=false\tscore=0"
            "\tcompleted_depth=8\toutcome=move\tcache_probes=0\tcache_hits=0\tcache_stores=0\n")
        seat.diagnostic_offset, seat.diagnostics, seat.cache_policies = 0, {}, {}
        seat.score_identities = {}
        seat.capture_cache_policy = False
        seat.collect_diagnostics()
        self.assertNotIn("exact_cache_policy", seat.diagnostics["p"])


if __name__ == "__main__":
    unittest.main()
