import json
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optimizer_adam as adam
import training as tr


KEY = '0/0/0'


def baseline(value=0):
    return {'weights': {'0': [{str(0): value}] + [{} for _ in range(63)]}}


class OptimizerAdamTests(unittest.TestCase):
    def test_hand_calculated_batch_gradient_bias_correction_and_projection(self):
        config = adam.settings(learning_rate=.1, beta1=.5, beta2=.75, epsilon=1e-8, batch=2)
        base = baseline()
        rows = [([KEY], 1), ([KEY], 3)]
        state = adam.advance(adam.initial(base, config), config, rows, rows, base)
        # Mean squared error gradient at zero: (2*(-1)+2*(-3))/2 = -4.
        self.assertEqual(state['step'], 1)
        self.assertEqual(state['m'][KEY], -2)
        self.assertEqual(state['v'][KEY], 4)
        self.assertAlmostEqual(state['weights'][KEY], .1*4/(4+1e-8))
        boundary = baseline(1)
        state = adam.advance(adam.initial(boundary, config), config,
                             [([KEY], 2)], rows, boundary)
        self.assertEqual(state['weights'][KEY], 1)

    def test_second_step_uses_global_bias_correction(self):
        config = adam.settings(learning_rate=.1, beta1=.5, beta2=.75, epsilon=.01, batch=1)
        base = baseline()
        rows = [([KEY], 1), ([KEY], 1)]
        first = adam.advance(adam.initial(base, config), config, rows, rows, base)
        second = adam.advance(first, config, rows, rows, base)
        gradient = 2*(first['weights'][KEY]-1)
        m = .5*(-1)+.5*gradient
        v = .75*1+.25*gradient**2
        expected = first['weights'][KEY]-.1*(m/(1-.5**2))/(math.sqrt(v/(1-.75**2))+.01)
        self.assertAlmostEqual(second['m'][KEY], m)
        self.assertAlmostEqual(second['v'][KEY], v)
        self.assertAlmostEqual(second['weights'][KEY], expected)

    def test_absent_batch_parameter_retains_zero_gradient_momentum_update(self):
        config = adam.settings(learning_rate=.1, beta1=.5, beta2=.75, epsilon=.01, batch=1)
        base = baseline()
        rows = [([KEY], 1), (['0/1/1'], 1)]
        first = adam.advance(adam.initial(base, config), config, rows, rows, base)
        first_key = rows[first['order'][0]][0][0]
        second = adam.advance(first, config, rows, rows, base)
        m = .5*first['m'][first_key]
        v = .75*first['v'][first_key]
        expected = first['weights'][first_key]-.1*(m/(1-.5**2))/(math.sqrt(v/(1-.75**2))+.01)
        self.assertAlmostEqual(second['m'][first_key], m)
        self.assertAlmostEqual(second['v'][first_key], v)
        self.assertAlmostEqual(second['weights'][first_key], expected)

    def test_half_away_export_drops_zero_and_preserves_unseen_baseline_weights(self):
        self.assertEqual([adam.rounded(n) for n in (-1, -.5, -.499, 0, .499, .5, 1)],
                         [-1, -1, 0, 0, 0, 1, 1])
        tables = adam.integer_weights({'0/0/0': .49, '0/1/1': -.5, '1/2/2': .5})
        self.assertEqual(tables['0'][0], {})
        self.assertEqual(tables['0'][1], {'1': -1})
        self.assertEqual(tables['1'][2], {'2': 1})
        config = adam.settings(batch=1, epochs=2)
        base = baseline(1)
        rows = [(['0/1/2'], 1)]
        state = adam.initial(base, config)
        while not state['done']:
            state = adam.advance(state, config, rows, rows, base)
        self.assertEqual(state['weights'][KEY], 1)
        self.assertNotIn(KEY, state['m'])

    def test_every_batch_and_epoch_boundary_resumes_identically(self):
        config = adam.settings(batch=2, epochs=3, patience=3)
        base = baseline()
        rows = [([KEY, '0/1/1'], target) for target in (-2, -1, 1, 2, 3)]
        states = [adam.initial(base, config)]
        while not states[-1]['done']:
            states.append(adam.advance(states[-1], config, rows, rows, base))
        self.assertTrue(any(state['cursor'] == len(rows) for state in states))
        self.assertTrue(any(state['epoch'] > 0 and not state['order'] for state in states))
        for index, saved in enumerate(states):
            with self.subTest(checkpoint=index):
                resumed = json.loads(tr.canonical_json(saved))
                while not resumed['done']:
                    resumed = adam.advance(resumed, config, rows, rows, base)
                self.assertEqual(resumed, states[-1])

    def test_float_improvement_cannot_break_integer_ties_or_reset_patience(self):
        config = adam.settings(batch=1, epochs=20, patience=2)
        base = baseline()
        rows = [([KEY], 1)]
        state = adam.initial(base, config)
        while not state['done']:
            state = adam.advance(state, config, rows, rows, base)
        self.assertEqual(state['epoch'], 3)
        self.assertEqual(state['best_epoch'], 1)
        self.assertEqual(state['stale'], 2)
        reports = state['epochs']
        self.assertEqual([report['integer_validation_mse'] for report in reports], [1, 1, 1])
        self.assertGreater(reports[0]['float_validation_mse'], reports[1]['float_validation_mse'])
        self.assertGreater(reports[1]['float_validation_mse'], reports[2]['float_validation_mse'])
        self.assertEqual(reports[-1]['rounded_away_changes'], 1)

    def test_nonfinite_invalid_and_changed_settings_fail_closed(self):
        for overrides in ({'learning_rate': float('nan')}, {'epsilon': float('inf')},
                          {'beta1': 1}, {'beta2': -1}, {'l2': .1}, {'batch': 0},
                          {'epochs': 21}, {'seed': -1}, {'patience': 0}, {'unexpected': 1}):
            with self.subTest(settings=overrides), self.assertRaises(tr.TrainingError):
                adam.settings(**overrides)
        for value in (float('nan'), float('inf'), 1.01):
            with self.subTest(weight=value), self.assertRaises(tr.TrainingError):
                adam.rounded(value)
        config = adam.settings()
        state = adam.initial(baseline(), config)
        changed = dict(config, learning_rate=.1)
        with self.assertRaisesRegex(tr.TrainingError, 'changed optimizer settings'):
            adam.advance(state, changed, [([KEY], 1)], [([KEY], 1)], baseline())
        with self.assertRaises(tr.TrainingError):
            adam.advance(state, config, [([KEY], float('nan'))], [([KEY], 1)], baseline())


if __name__ == '__main__':
    unittest.main()
