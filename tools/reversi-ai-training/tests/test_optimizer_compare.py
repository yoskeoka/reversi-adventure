"""Small end-to-end arithmetic/receipt fixtures; never production batches."""
import argparse
import copy
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import optimizer_adam as adam
import optimizer_compare as compare
import reinforcement as rf
import training as tr


class ComparisonTests(unittest.TestCase):
    def fixture(self, root):
        path = Path(tr.__file__).parent/'fixtures/tiny-winner-empty-manifest.json'
        manifest = tr.read_json(path)
        rows = tr.validate_records(tr.validate_manifest(manifest, path.parent))
        base = tr.artifact_from(manifest, rows, tr.digest(manifest))
        teachers = [dict(id='teacher', board=rf.INITIAL, side='B', target=1)]
        validation = [dict(id='validation', board=rf.INITIAL, side='B', target=1)]
        # Independent real split checks belong to input tests; this deliberately
        # small same-feature fixture isolates export losing float improvements.
        context = dict(baseline=base, adopted=base, teachers=teachers, validation=validation,
                       held_out=validation, pins={}, split_audit={}, source_context={'manifest': {} })
        config = adam.settings(epochs=3, patience=2, learning_rate=.001)
        frozen = dict(schema_version=1, producer=compare.VERSION, source={}, optimizer=config,
                      matches={}, sources=compare.source_hashes(), execution_commit='a'*40)
        root.mkdir()
        compare.write_once(root, 'manifest.json', compare.seal(frozen))
        for name in ('teachers', 'validation', 'held_out'):
            compare.write_once(root, name+'.json', context[name])
        compare.write_once(root, 'split-audit.json', {})
        compare.write_once(root, 'prepare.receipt.json', compare.seal(compare.preparation_evidence(root)))
        stack = ExitStack()
        self.addCleanup(stack.close)
        stack.enter_context(mock.patch.object(compare.inputs, 'load_pinned', return_value=context))
        stack.enter_context(mock.patch.object(compare.matches, 'validate_settings'))
        stack.enter_context(mock.patch.object(compare.cycle, 'source_commit', return_value='a'*40))
        stack.enter_context(mock.patch.object(compare.rf, 'updated_artifact', return_value=base))
        return frozen, context

    def args(self, root, phase=None):
        return argparse.Namespace(run_root=root, progress_every=10, resume_from=phase)

    def test_float_improvement_integer_tie_skips_all_games_and_offline_is_read_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'compare'
            _, context = self.fixture(root)
            with mock.patch.object(compare.matches, 'run', side_effect=AssertionError('must skip matches')):
                report = compare.run(self.args(root))
            self.assertEqual(report['outcome'], 'not-improved')
            self.assertFalse(report['selection']['validation_improved'])
            self.assertEqual(report['matches']['comparison']['games'], 0)
            epoch = report['selection']['epochs'][0]
            self.assertLess(epoch['float_validation_mse'], epoch['integer_validation_mse'])
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with mock.patch.object(rf, 'Candidate', side_effect=AssertionError('offline process')):
                self.assertEqual(compare.verify(root), report)
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})

    def test_resume_after_interrupted_batch_matches_uninterrupted_arithmetic(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'compare'
            frozen, context = self.fixture(root)
            original = compare.write_once
            def interrupt(folder, name, value):
                if folder.name == 'checkpoints' and name == '000002.json':
                    raise OSError('interrupted checkpoint publication')
                return original(folder, name, value)
            with mock.patch.object(compare, 'write_once', side_effect=interrupt):
                with self.assertRaisesRegex(OSError, 'interrupted'):
                    compare.run(self.args(root))
            self.assertEqual(len(compare.checkpoints(root)), 2)
            report = compare.run(self.args(root, 'optimization'))
            state, best, _ = compare.validate_states(root, frozen, context)
            train, validation = compare.cached(context)
            expected = adam.initial(context['baseline'], frozen['optimizer'])
            while not expected['done']:
                expected = adam.advance(expected, frozen['optimizer'], train, validation, context['baseline'])
            state['training_seconds'] = 0
            self.assertEqual(state, expected)
            self.assertEqual(report['selection']['best_epoch'], 1)
            self.assertTrue((root/'failure-0000.json').exists())

    def test_resealed_bad_state_and_final_receipt_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)/'compare'
            self.fixture(root)
            compare.run(self.args(root))
            path = root/'offline-verification.receipt.json'
            original = path.read_bytes()
            value = compare.unseal(path)
            value['data']['report_sha256'] = '0'*64
            path.write_bytes(compare.blob(compare.seal(value)))
            with self.assertRaisesRegex(tr.TrainingError, 'changed immutable'):
                compare.verify(root)
            path.write_bytes(original)
            checkpoint = root/'checkpoints/000001.json'
            value = compare.unseal(checkpoint)
            value['state']['cursor'] = 999
            checkpoint.write_bytes(compare.blob(compare.seal(value)))
            with self.assertRaisesRegex(tr.TrainingError, 'transition mismatch'):
                compare.verify(root)

    def test_verdict_requires_every_gate_including_zero_regret(self):
        self.assertTrue(compare.within(11, 10))
        self.assertFalse(compare.within(12, 10))
        selected = dict(validation_improved=True, held_out=dict(control_mse=0, candidate_mse=0))
        match = dict(comparison=dict(games=20, match_points=10.5), oracle={},
                     corpus=dict(status='complete', candidate=dict(mean_regret=0), baseline=dict(mean_regret=0)))
        self.assertEqual(compare.final_report(selected, match)['outcome'], 'improved')
        for field, value in (('match_points', 10), ('games', 19)):
            changed = copy.deepcopy(match)
            changed['comparison'][field] = value
            self.assertEqual(compare.final_report(selected, changed)['outcome'], 'not-improved')
        match['corpus']['candidate']['mean_regret'] = .0001
        self.assertEqual(compare.final_report(selected, match)['outcome'], 'not-improved')


if __name__ == '__main__':
    unittest.main()
