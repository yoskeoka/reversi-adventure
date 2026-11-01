import copy
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import table32_optimizer as opt


def identity(index):
    return index


class Table32AdamTests(unittest.TestCase):
    def initial(self, rows=None, validation=(), **kwargs):
        return opt.initial_state(rows or [{"features": [0], "target": 1}], validation,
                                 phase=0, reverse_index=identity, **kwargs)

    def test_first_step_matches_hand_computation_epsilon_placement(self):
        rows = [{"features": [0], "target": 1}]
        initial = self.initial(rows)
        self.assertEqual(initial["counts"], [2])
        state = opt.train_step(initial, rows)
        # target32; residual twice32; gradient128; m12.8; v16.384.
        m = (1 - .9) * 128
        v = (1 - .999) * 128 ** 2
        lrt = 150 * math.sqrt(1 - .999) / (1 - .9)
        self.assertAlmostEqual(state["weights"][0], lrt * m / (math.sqrt(v) + 1e-7), places=12)
        self.assertEqual(state["m"], [m])
        self.assertEqual(state["v"], [v])
        self.assertEqual(initial["step"], 0)
        self.assertEqual(state["predecessor_sha256"], opt.state_digest(initial))

    def test_count_cap_and_reverse_pair_addition(self):
        rows = [{"features": [0, 1] * 30, "target": 2}]
        state = opt.initial_state(rows, phase=12, reverse_index=lambda i: 1 - i)
        self.assertEqual(state["counts"], [60, 60])
        self.assertEqual(state["capped_counts"], [50, 50])
        state = opt.train_step(state, rows)
        self.assertEqual(state["weights"][0], state["weights"][1])
        self.assertAlmostEqual(state["weights"][0], 6, places=6)
        self.assertEqual(state["indices"], [0, 1])  # no unobserved allocation

    def test_prediction_is_clipped_before_residual(self):
        rows = [{"features": [0] * 65, "target": 64}]
        state = self.initial(rows)
        state["weights"] = [4091.0]
        state = opt.train_step(state, rows)
        self.assertEqual(state["weights"], [4091.0])
        self.assertEqual(state["m"], [0.0])
        self.assertEqual(state["train_loss"]["mse"], 0)

    def test_no_derivative_suppression_at_clipped_prediction(self):
        rows = [{"features": [0] * 65, "target": 63}]
        state = self.initial(rows)
        state["weights"] = [4091.0]
        updated = opt.train_step(state, rows)
        self.assertLess(updated["weights"][0], 4091)

    def test_parameter_limit(self):
        rows = [{"features": [0], "target": 64}]
        state = self.initial(rows)
        state["weights"] = [4090.0]
        # target is clipped2048, initial raw4090: zero residual.  A negative
        # stored momentum still updates a zero-gradient coordinate.
        state["weights"] = [-4090.0]
        state["m"], state["v"] = [-1e10], [1e20]
        result = opt.train_step(state, rows)
        self.assertEqual(result["weights"], [-4091])

    def test_equal_validation_resets_both_counters(self):
        rows = [{"features": [0], "target": 1}]
        state = self.initial(rows, rows)
        state["best_validation_mse"] = 1.0
        state["worse_count"], state["lr_worse_count"] = 12, 9
        updated = opt.train_step(state, rows, rows)
        self.assertEqual((updated["worse_count"], updated["lr_worse_count"]), (0, 0))
        self.assertEqual(updated["alpha"], 300)

    def test_validation_stop_precedes_step_and_lr_change_follows_step(self):
        rows = [{"features": [0], "target": 1}]
        state = self.initial(rows, rows)
        state["best_validation_mse"] = 0.0
        state["worse_count"], state["lr_worse_count"] = 100, 9
        stopped = opt.train_step(state, rows, rows)
        self.assertEqual(stopped["step"], 0)
        self.assertEqual(stopped["stop_reason"], "validation-patience")
        state["worse_count"] = 9
        reduced = opt.train_step(state, rows, rows)
        self.assertEqual(reduced["alpha"], 210)
        self.assertAlmostEqual(reduced["weights"][0], 150, places=5)

    def test_missing_validation_is_not_missing_train(self):
        with self.assertRaisesRegex(ValueError, "training-phase-unavailable"):
            opt.initial_state([], phase=0, reverse_index=identity)
        rows = [{"features": [0], "target": 0}]
        result = opt.train_phase(rows, phase=0, reverse_index=identity, max_steps=3)
        self.assertEqual(result["validation_status"], "validation-unavailable")
        self.assertEqual(result["step"], 3)
        self.assertEqual(result["stop_reason"], "step-limit")

    def test_continuous_and_resumed_arithmetic_identical_offline(self):
        rows = [{"features": [0], "target": 1}]
        final = opt.train_phase(rows, phase=0, reverse_index=identity, max_steps=4)
        prefix = opt.train_step(self.initial(rows, max_steps=4), rows)
        resumed = opt.train_phase(rows, phase=0, state=json.loads(json.dumps(prefix)), max_steps=4)
        self.assertEqual(opt.state_digest(final), opt.state_digest(resumed))
        with patch("subprocess.Popen", side_effect=AssertionError("no subprocess")):
            self.assertEqual(opt.verify_training(final, rows, reverse_index=identity), opt.state_digest(final))
        tampered = copy.deepcopy(final)
        tampered["weights"][0] += 1
        with self.assertRaisesRegex(ValueError, "replay mismatch"):
            opt.verify_training(tampered, rows, reverse_index=identity)

    def test_reject_nonfinite_and_changed_inputs_or_limits(self):
        rows = [{"features": [0], "target": 1}]
        for value in (math.nan, math.inf, -math.inf):
            with self.assertRaises(ValueError):
                self.initial([{"features": [0], "target": value}])
        with self.assertRaises(ValueError):
            self.initial(rows, max_steps=0)
        with self.assertRaisesRegex(ValueError, "identity mismatch"):
            opt.train_step(self.initial(rows), [{"features": [0], "target": 2}])
        state = self.initial(rows)
        state["v"][0] = float("nan")
        with self.assertRaisesRegex(ValueError, "nonfinite"):
            opt.train_step(state, rows)

    def test_explicit_scale_override_is_frozen_in_state(self):
        rows = [{"features": [0], "target": 0}]
        state = self.initial(rows, max_steps=2000)
        self.assertEqual(state["max_steps"], 2000)
        self.assertEqual(self.initial(rows)["max_steps"], 1000)
        with self.assertRaisesRegex(ValueError, "settings require a new root"):
            opt.train_phase(rows, phase=0, state=state, max_steps=1000)


class Table32ExportTests(unittest.TestCase):
    def trained(self, rows, weight):
        state = opt.initial_state(rows, phase=0, reverse_index=identity, max_steps=1)
        state = opt.train_step(state, rows)
        state["weights"] = [weight]
        return state

    def test_raw32_half_rounding_sum_before_division_and_clip(self):
        expected = {15: 0, 16: 1, 31: 1, 32: 1, 48: 2, -15: 0, -16: -1, -48: -2,
                    65 * 4091: 64, -65 * 4091: -64}
        for raw, score in expected.items():
            self.assertEqual(opt.runtime_score(raw), score)
        self.assertEqual(opt.runtime_score(15 + 15), 1)
        self.assertEqual(opt.runtime_score(15) + opt.runtime_score(15), 0)

    def test_f32_floor_ceil_with_f64_initial_round(self):
        self.assertEqual(opt.round_candidates(0.999999999), (1, 1, True))
        self.assertEqual(opt.round_candidates(-0.999999999), (-1, -1, True))
        self.assertEqual(opt.round_candidates(.5), (0, 1, False))
        self.assertEqual(opt.round_candidates(-.5), (-1, 0, True))

    def test_self_pair_flips_once_and_loss_guided_integer_export(self):
        rows = [{"features": [0] * 65, "target": 0}]
        state = opt.initial_export(self.trained(rows, .51), rows, seed=7, parameter_count=1)
        self.assertEqual(state["loss"]["squared_error"], 4)
        updated = opt.export_step(state, rows)
        self.assertEqual(updated["loss"]["squared_error"], 0)
        self.assertEqual(updated["improvements"], 1)
        self.assertTrue(updated["last_accepted"])
        self.assertTrue(updated["round_down"][0])
        rejected = opt.export_step(updated, rows)
        self.assertFalse(rejected["last_accepted"])
        self.assertEqual(rejected["loss"], updated["loss"])

    def test_nonworsening_flip_accepted_but_not_an_improvement(self):
        rows = [{"features": [0], "target": 0}]
        state = opt.initial_export(self.trained(rows, .49), rows, seed=7, parameter_count=1)
        updated = opt.export_step(state, rows)
        self.assertTrue(updated["last_accepted"])
        self.assertEqual(updated["updates"], 1)
        self.assertEqual(updated["improvements"], 0)

    def test_export_uses_runtime_loss_even_when_raw32_error_improves(self):
        rows = [{"features": [0], "target": 1}]
        state = opt.initial_export(self.trained(rows, .49), rows, seed=7, parameter_count=1)
        self.assertEqual(state["loss"]["squared_error"], 1)
        updated = opt.export_step(state, rows)
        # 0 -> 1 reduces raw32 SSE from32**2 to31**2. Both summed
        # predictions round to runtime score0, so source export counts a tie.
        self.assertEqual(opt.exported_weights(updated, require_complete=False), {0: 1})
        self.assertEqual(updated["loss"]["squared_error"], 1)
        self.assertTrue(updated["last_accepted"])
        self.assertEqual(updated["updates"], 1)
        self.assertEqual(updated["improvements"], 0)

    def test_tied_acceptances_do_not_keep_export_running(self):
        rows = [{"features": [0], "target": 1}]
        state = opt.initial_export(self.trained(rows, .49), rows, seed=7, parameter_count=1)
        for _ in range(100):
            state = opt.export_step(state, rows)
        self.assertEqual(state["updates"], 100)
        self.assertEqual(state["improvements"], 0)
        self.assertEqual(state["tries"], 100)
        self.assertTrue(state["complete"])
        self.assertEqual(state["stop_reason"], "improvement-rate")

    def test_integer_only_draws_count_and_rate_stop_requires_100(self):
        rows = [{"features": [0], "target": 0}]
        state = opt.initial_export(self.trained(rows, 0.0), rows, seed=7, parameter_count=1)
        for _ in range(99):
            state = opt.export_step(state, rows)
        self.assertFalse(state["complete"])
        state = opt.export_step(state, rows)
        self.assertTrue(state["complete"])
        self.assertEqual(state["tries"], 100)
        self.assertEqual(state["stop_reason"], "improvement-rate")

    def test_export_resume_and_independent_replay(self):
        rows = [{"features": [0] * 65, "target": 0}]
        training = self.trained(rows, .51)
        initial = opt.initial_export(training, rows, seed=2, parameter_count=1, max_proposals=10)
        continuous = opt.run_export(initial, rows)
        prefix = opt.export_step(initial, rows)
        resumed = opt.run_export(json.loads(json.dumps(prefix)), rows)
        self.assertEqual(opt.state_digest(continuous), opt.state_digest(resumed))
        self.assertEqual(opt.exported_weights(continuous), {})
        with patch("subprocess.Popen", side_effect=AssertionError("no subprocess")):
            opt.verify_export(continuous, training, rows)
        modified = copy.deepcopy(continuous)
        modified["improvements"] += 1
        with self.assertRaisesRegex(ValueError, "replay mismatch"):
            opt.verify_export(modified, training, rows)

    def test_unfinished_export_and_wall_pause(self):
        rows = [{"features": [0], "target": 0}]
        state = opt.initial_export(self.trained(rows, .1), rows, seed=4, parameter_count=1)
        with self.assertRaisesRegex(ValueError, "unfinished"):
            opt.exported_weights(state)
        with patch.object(opt.time, "monotonic", side_effect=[0, 61]):
            paused = opt.run_export(state, rows)
        self.assertEqual(paused, state)
        self.assertFalse(paused["complete"])

    def test_explicit_export_scale_override(self):
        rows = [{"features": [0], "target": 0}]
        training = self.trained(rows, .1)
        state = opt.initial_export(training, rows, seed=4, parameter_count=1,
                                   max_proposals=2000)
        self.assertEqual(state["max_proposals"], 2000)
        self.assertEqual(opt.initial_export(training, rows, seed=4, parameter_count=1)["max_proposals"], 1000)


if __name__ == "__main__":
    unittest.main()
