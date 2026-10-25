"""Human-operated, frozen-input optimizer comparison and offline verification."""
from __future__ import annotations

import argparse
import copy
import math
import sys
import time
from fractions import Fraction
from pathlib import Path

import optimizer_adam as adam
import optimizer_compare_inputs as inputs
import optimizer_compare_matches as matches
import production_cycle as cycle
import reinforcement as rf
import training as tr

PHASES = ('input-verification', 'control-reproduction', 'optimization',
          'integer-selection', 'matches', 'offline-verification')
VERSION = 'optimizer-compare-v1'


def blob(value):
    return tr.canonical_json(value)+b'\n'


def write_once(root, name, value):
    path = root/name
    if path.exists():
        adam.require(path.read_bytes() == blob(value), f'changed immutable output {path}')
    else:
        rf.atomic_write(root, name, blob(value))


def seal(value):
    result = copy.deepcopy(value)
    result['digest'] = tr.digest(result)
    return result


def unseal(path):
    value = tr.read_json(path)
    expected = dict(value)
    digest = expected.pop('digest', None)
    adam.require(digest == tr.digest(expected), f'changed saved output {path}')
    return expected


class Progress:
    def __init__(self, config, teacher_count, every=10):
        self.config, self.every = config, every
        self.batches = math.ceil(teacher_count/config['batch'])*config['epochs']
        self.started = time.monotonic()

    def requested(self):
        print(f"optimizer-compare requested_epochs={self.config['epochs']} "
              f'maximum_batches={self.batches} comparison_games=20 oracle_games=20', file=sys.stderr, flush=True)

    def emit(self, phase, state=None, games=0, total=40):
        state = state or {}
        print(f"optimizer-compare phase={phase} epoch={state.get('epoch', 0)}/{self.config['epochs']} "
              f"batch={state.get('step', 0)}/{self.batches} games={games}/{total} "
              f"elapsed_seconds={time.monotonic()-self.started:.3f}", file=sys.stderr, flush=True)


def source_hashes():
    return {name: tr.sha256_file(Path(__file__).with_name(name)) for name in (
        'optimizer_compare.py', 'optimizer_adam.py', 'optimizer_compare_inputs.py',
        'optimizer_compare_matches.py', 'training.py', 'reinforcement.py', 'production_cycle.py', 'pilot.py')}


def prepare(args):
    root = args.run_root.resolve()
    checkout = Path(__file__).resolve().parents[2]
    source_root = args.source_manifest.resolve().parent
    adam.require(args.run_root.is_absolute() and root != checkout and checkout not in root.parents,
                 'comparison run root must be absolute and outside checkout')
    adam.require(root != source_root and source_root not in root.parents and root not in source_root.parents,
                 'comparison and source roots must be separate')
    adam.require(not root.exists(), 'comparison run root exists; resume or choose a new root')
    config = adam.settings(learning_rate=args.learning_rate, batch=args.batch, epochs=args.epochs,
                           seed=args.seed, patience=args.patience)
    progress = Progress(config, 3364)
    progress.requested()
    progress.emit('prepare')
    context = inputs.load_source(args.source_manifest)
    setting = matches.prepare(context, args.seed, args.candidate_executable,
                              args.oracle_binary, args.decision_timeout_seconds)
    manifest = seal(dict(schema_version=1, producer=VERSION, source=context['pins'],
                         optimizer=config, matches=setting, sources=source_hashes(),
                         execution_commit=cycle.source_commit()))
    root.mkdir(parents=True, exist_ok=False)
    write_once(root, 'manifest.json', manifest)
    write_once(root, 'split-audit.json', context['split_audit'])
    # Snapshot admitted rows with provenance; source inputs remain pinned and untouched.
    for name in ('teachers', 'validation', 'held_out'):
        write_once(root, name+'.json', context[name])
    write_once(root, 'prepare.receipt.json', seal(preparation_evidence(root)))
    return manifest


def preparation_evidence(root):
    return dict(manifest_sha256=tr.sha256_file(root/'manifest.json'),
                snapshots={name: tr.sha256_file(root/name) for name in
                           ('teachers.json', 'validation.json', 'held_out.json', 'split-audit.json')})


def load(root):
    manifest = unseal(root/'manifest.json')
    adam.require(manifest['schema_version'] == 1 and manifest['producer'] == VERSION,
                 'unsupported comparison manifest')
    adam.require(adam.settings(**manifest['optimizer']) == manifest['optimizer'], 'invalid optimizer settings')
    context = inputs.load_pinned(manifest['source'])
    matches.validate_settings(context, manifest['matches'])
    for name in ('teachers', 'validation', 'held_out'):
        adam.require((root/(name+'.json')).read_bytes() == blob(context[name]), f'changed {name} snapshot')
    adam.require((root/'split-audit.json').read_bytes() == blob(context['split_audit']), 'changed split audit')
    adam.require(unseal(root/'prepare.receipt.json') == preparation_evidence(root), 'changed preparation receipt')
    return manifest, context


def receipt(root, phase, data):
    previous = {}
    for name in PHASES[:PHASES.index(phase)]:
        path = root/(name+'.receipt.json')
        adam.require(path.is_file(), f'missing predecessor {name}')
        unseal(path)
        previous[name] = tr.sha256_file(path)
    value = seal(dict(phase=phase, manifest_sha256=tr.sha256_file(root/'manifest.json'),
                      predecessors=previous, data=data))
    write_once(root, phase+'.receipt.json', value)


def cached(context):
    if '_features' not in context:
        context['_features'] = (adam.features(context['teachers']), adam.features(context['validation']))
    return context['_features']


def checkpoints(root):
    folder = root/'checkpoints'
    return sorted(folder.glob('*.json')) if folder.exists() else []


def validate_states(root, manifest, context):
    """Check saved arithmetic transitions; never start a trainer or external program."""
    train, validation = cached(context)
    expected = adam.initial(context['baseline'], manifest['optimizer'])
    best, prior_digest = None, None
    for index, path in enumerate(checkpoints(root)):
        adam.require(path.name == f'{index:06}.json', 'missing or reordered completed batch')
        saved = unseal(path)
        adam.require(saved['previous'] == prior_digest, 'checkpoint chain mismatch')
        if index:
            expected = adam.advance(expected, manifest['optimizer'], train, validation, context['baseline'])
        state = saved['state']
        elapsed = state['training_seconds']
        adam.require(type(elapsed) in (int, float) and math.isfinite(elapsed)
                     and elapsed >= expected['training_seconds'], 'invalid training time')
        expected['training_seconds'] = elapsed
        adam.require(tr.canonical_json(state) == tr.canonical_json(expected), 'checkpoint transition mismatch')
        if state['epochs'] and not state['order'] and state['best_epoch'] == state['epoch']:
            best = copy.deepcopy(state)
        prior_digest = tr.sha256_file(path)
    return expected, best, prior_digest


def epoch_exports(root, manifest, context, *, publish=False):
    folder = root/'epochs'
    expected = set()
    for path in checkpoints(root):
        state = unseal(path)['state']
        if state['epochs'] and not state['order']:
            name = f"epoch-{state['epoch']:04}.json"
            expected.add(name)
            artifact = adam.artifact(state['weights'], context['baseline'],
                                     tr.digest(manifest), manifest['optimizer']['seed'])
            if publish:
                folder.mkdir(exist_ok=True)
                write_once(folder, name, artifact)
            else:
                adam.require((folder/name).is_file() and (folder/name).read_bytes() == blob(artifact),
                             'epoch integer export differs from float checkpoint')
    actual = {p.name for p in folder.iterdir()} if folder.exists() else set()
    adam.require(actual == expected, 'missing or unexpected epoch exports')
    return {name: tr.sha256_file(folder/name) for name in sorted(expected)}


def optimization_evidence(root, manifest, context):
    return dict(checkpoints={p.name: tr.sha256_file(p) for p in checkpoints(root)},
                integer_exports=epoch_exports(root, manifest, context))


def optimize(root, manifest, context, progress):
    config = manifest['optimizer']
    state, best, previous = validate_states(root, manifest, context)
    epoch_exports(root, manifest, context, publish=True)
    train, validation = cached(context)
    folder = root/'checkpoints'
    folder.mkdir(exist_ok=True)
    count = len(checkpoints(root))
    if not count:
        write_once(folder, '000000.json', seal(dict(previous=None, state=state)))
        previous, count = tr.sha256_file(folder/'000000.json'), 1
    while not state['done']:
        started = time.monotonic()
        state = adam.advance(state, config, train, validation, context['baseline'])
        state['training_seconds'] += time.monotonic()-started
        write_once(folder, f'{count:06}.json', seal(dict(previous=previous, state=state)))
        previous = tr.sha256_file(folder/f'{count:06}.json')
        count += 1
        if not state['order']:
            folder_epoch = root/'epochs'
            folder_epoch.mkdir(exist_ok=True)
            exported = adam.artifact(state['weights'], context['baseline'], tr.digest(manifest), config['seed'])
            write_once(folder_epoch, f"epoch-{state['epoch']:04}.json", exported)
            if state['best_epoch'] == state['epoch']:
                best = copy.deepcopy(state)
            progress.emit('optimization', state)
        elif state['step'] % progress.every == 0:
            progress.emit('optimization', state)
    adam.require(best is not None, 'missing best integer epoch')
    return state, best


def selection(manifest, context, state, best, control_seconds=0):
    train, validation = cached(context)
    baseline = adam.flat(context['adopted']['weights'])
    artifact = adam.artifact(best['weights'], context['baseline'],
                             tr.digest(manifest), manifest['optimizer']['seed'])
    exported = adam.flat(artifact['weights'])
    control = dict(train_mse=adam.metric(baseline, train), validation_mse=adam.metric(baseline, validation),
                   training_seconds=control_seconds)
    diagnostic_state = dict(weights=baseline)
    control['diagnostics'] = adam.diagnostics(diagnostic_state, context['baseline'], train, validation)
    # Held-out is accessed only after epoch selection has finished.
    held = adam.features(context['held_out'])
    report = dict(best_epoch=best['epoch'], epochs=state['epochs'],
                  training_seconds=state['training_seconds'], control=control,
                  candidate=dict(train_mse=adam.metric(exported, train),
                                 validation_mse=adam.metric(exported, validation)),
                  held_out=dict(control_mse=adam.metric(baseline, held), candidate_mse=adam.metric(exported, held),
                                records=len(held),
                                control_sum_squared_error=int(sum((sum(baseline.get(k, 0) for k in keys)-target)**2 for keys, target in held)),
                                candidate_sum_squared_error=int(sum((sum(exported.get(k, 0) for k in keys)-target)**2 for keys, target in held))),
                  validation_improved=adam.metric(exported, validation) < control['validation_mse'])
    return artifact, report


def control(root, context, *, verify_only=False):
    path = root/'control.json'
    if not path.exists():
        adam.require(not verify_only, 'missing control timing evidence')
        started = time.monotonic()
        artifact = rf.updated_artifact(context['baseline'], context['teachers'], context['source_context']['manifest'])
        elapsed = time.monotonic()-started
        adam.require(artifact['weights'] == context['adopted']['weights']
                     and artifact['weight_digest'] == context['adopted']['weight_digest'], 'control A did not reproduce')
        write_once(root, 'control.json', dict(weight_digest=artifact['weight_digest'], training_seconds=elapsed))
    value = tr.read_json(path)
    adam.require(set(value) == {'weight_digest', 'training_seconds'}
                 and value['weight_digest'] == context['adopted']['weight_digest']
                 and type(value['training_seconds']) in (int, float)
                 and math.isfinite(value['training_seconds']) and value['training_seconds'] >= 0,
                 'invalid control diagnostics')
    return value


def within(candidate, control):
    return Fraction(str(candidate))*10 <= Fraction(str(control))*11 if control else candidate == 0


def final_report(selected, match_report):
    corpus = match_report['corpus']
    corpus_ok = corpus['status'] == 'complete' and within(
        corpus['candidate'].get('sum_regret', corpus['candidate']['mean_regret']),
        corpus['baseline'].get('sum_regret', corpus['baseline']['mean_regret']))
    comparison = match_report['comparison']
    held = selected['held_out']
    gates = dict(validation=selected['validation_improved'], held_out=within(
                    held.get('candidate_sum_squared_error', held['candidate_mse']),
                    held.get('control_sum_squared_error', held['control_mse'])),
                 corpus=corpus_ok, comparison=comparison['games'] == 20 and comparison['match_points'] > 10)
    improved = all(gates.values())
    return dict(producer=VERSION, status='complete', selection=selected, matches=match_report,
                outcome='improved' if improved else 'not-improved',
                gates=gates, reasons=[f'{name} gate did not pass' for name, passed in gates.items() if not passed],
                adopted_model_replaced=False, acceptance_0018=False)


def verify(root, *, publishing=False):
    manifest, context = load(root)
    state, best, _ = validate_states(root, manifest, context)
    adam.require(state['done'] and best is not None, 'comparison optimization incomplete')
    expected_artifact, selected = selection(manifest, context, state, best,
                                             control(root, context, verify_only=True)['training_seconds'])
    adam.require((root/'candidate-artifact.json').read_bytes() == blob(expected_artifact), 'integer artifact differs from selected checkpoint')
    adam.require((root/'selection.json').read_bytes() == blob(selected), 'changed integer selection')
    if selected['validation_improved']:
        match_report = matches.verify(context, manifest['matches'], root/'candidate-artifact.json', root/'matches')
    else:
        match_report = matches.skipped('integer validation MSE did not strictly improve')
        adam.require(not (root/'matches').exists(), 'matches were executed despite failed validation gate')
    expected = final_report(selected, match_report)
    for phase, data in (
            ('input-verification', dict(pins=manifest['source'], split_audit_digest=tr.digest(context['split_audit']))),
            ('control-reproduction', control(root, context, verify_only=True)),
            ('optimization', optimization_evidence(root, manifest, context)),
            ('integer-selection', selected), ('matches', match_report)):
        path = root/(phase+'.receipt.json')
        adam.require(path.exists(), f'missing phase receipt {phase}')
        # Recreate expected receipts without rewriting prior evidence.
        receipt(root, phase, data)
    adam.require((root/'report.json').read_bytes() == blob(expected), 'changed final report')
    final = root/'offline-verification.receipt.json'
    if not publishing:
        adam.require(final.exists(), 'missing offline verification receipt')
    if final.exists():
        receipt(root, 'offline-verification', dict(report_sha256=tr.sha256_file(root/'report.json')))
    return expected


def run(args):
    root = args.run_root.resolve()
    preview = unseal(root/'manifest.json')
    progress = Progress(adam.settings(**preview['optimizer']), 3364, args.progress_every)
    progress.requested()
    progress.emit('input-verification')
    manifest, context = load(root)
    adam.require(manifest['sources'] == source_hashes(), 'trainer source changed; use a new comparison root')
    adam.require(manifest['execution_commit'] == cycle.source_commit(), 'execution commit changed; use a new comparison root')
    adam.require(not (root/'offline-verification.receipt.json').exists(), 'comparison already completed; use verify')
    progress.batches = math.ceil(len(context['teachers'])/manifest['optimizer']['batch'])*manifest['optimizer']['epochs']
    start = args.resume_from or PHASES[0]
    for phase in PHASES[:PHASES.index(start)]:
        adam.require((root/(phase+'.receipt.json')).is_file(), f'resume missing predecessor {phase}')
        unseal(root/(phase+'.receipt.json'))
    try:
        progress.emit('input-verification')
        receipt(root, 'input-verification', dict(pins=manifest['source'], split_audit_digest=tr.digest(context['split_audit'])))
        progress.emit('control-reproduction')
        receipt(root, 'control-reproduction', control(root, context))
        progress.emit('optimization')
        state, best = optimize(root, manifest, context, progress)
        receipt(root, 'optimization', optimization_evidence(root, manifest, context))
        progress.emit('integer-selection', state)
        artifact, selected = selection(manifest, context, state, best, control(root, context)['training_seconds'])
        write_once(root, 'candidate-artifact.json', artifact)
        write_once(root, 'selection.json', selected)
        receipt(root, 'integer-selection', selected)
        progress.emit('matches', state)
        if selected['validation_improved']:
            match_report = matches.run(context, manifest['matches'], root/'candidate-artifact.json', root/'matches',
                lambda phase, completed, total: progress.emit(phase, state, completed, total))
        else:
            match_report = matches.skipped('integer validation MSE did not strictly improve')
        receipt(root, 'matches', match_report)
        write_once(root, 'report.json', final_report(selected, match_report))
        progress.emit('offline-verification', state)
        report = verify(root, publishing=True)
        receipt(root, 'offline-verification', dict(report_sha256=tr.sha256_file(root/'report.json')))
        print(f"optimizer-compare verified report={root/'report.json'} digest={tr.digest(report)}")
        return report
    except BaseException as error:
        # Preserve every checkpoint, completed game and previous failure record.
        count = len(list(root.glob('failure-*.json')))
        write_once(root, f'failure-{count:04}.json', dict(error=str(error), manifest_sha256=tr.sha256_file(root/'manifest.json')))
        raise


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='action', required=True)
    prep = commands.add_parser('prepare')
    for name in ('run-root', 'source-manifest', 'candidate-executable', 'oracle-binary'):
        prep.add_argument('--'+name, type=Path, required=True)
    prep.add_argument('--learning-rate', type=float, default=.01)
    prep.add_argument('--batch', type=int, default=256)
    prep.add_argument('--epochs', type=int, default=20)
    prep.add_argument('--seed', type=int, default=20261025)
    prep.add_argument('--patience', type=int, default=5)
    prep.add_argument('--decision-timeout-seconds', type=int, required=True)
    for action in ('run', 'verify'):
        sub = commands.add_parser(action)
        sub.add_argument('--run-root', type=Path, required=True)
        sub.add_argument('--progress-every', type=rf.positive_interval, default=10)
        if action == 'run':
            sub.add_argument('--resume-from', choices=PHASES)
    args = parser.parse_args(argv)
    if args.action == 'prepare':
        prepare(args)
    elif args.action == 'run':
        run(args)
    else:
        report = verify(args.run_root.resolve())
        print(f'optimizer-compare offline verified digest={tr.digest(report)}')
    return 0
