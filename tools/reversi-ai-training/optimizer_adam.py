"""Deterministic projected Adam arithmetic and independently checkable states."""
from __future__ import annotations

import copy
import math
import random
from collections import Counter

import training as tr


def require(condition, message):
    if not condition:
        raise tr.TrainingError(message)


def settings(**overrides):
    value = dict(learning_rate=.01, beta1=.9, beta2=.999, epsilon=1e-8,
                 l2=0, batch=256, epochs=20, seed=20261025, patience=5)
    value.update(overrides)
    require(set(value) == {'learning_rate', 'beta1', 'beta2', 'epsilon', 'l2',
                           'batch', 'epochs', 'seed', 'patience'}, 'unknown Adam setting')
    for name in ('learning_rate', 'beta1', 'beta2', 'epsilon', 'l2'):
        require(type(value[name]) in (float, int) and math.isfinite(value[name]),
                f'non-finite Adam {name}')
    require(0 < value['learning_rate'] <= 1 and value['epsilon'] > 0
            and 0 <= value['beta1'] < 1 and 0 <= value['beta2'] < 1
            and value['l2'] == 0, 'invalid Adam arithmetic settings')
    for name, minimum, maximum in (('batch', 1, 3364), ('epochs', 1, 20),
                                    ('seed', 0, 2**64-1), ('patience', 1, 20)):
        tr.require_int(value[name], name, minimum, maximum)
    return value


def flat(weights):
    return {f'{phase}/{feature}/{code}': float(value)
            for phase, tables in weights.items() for feature, table in enumerate(tables)
            for code, value in table.items()}


def features(rows):
    require(bool(rows), 'empty comparison split')
    result = []
    for row in rows:
        phase, codes = tr.extract_features(row['board'], row['side'])
        result.append(([f'{phase}/{i}/{code}' for i, code in enumerate(codes)], row['target']))
    return result


def metric(weights, rows):
    errors = [(sum(weights.get(key, 0) for key in keys)-target)**2 for keys, target in rows]
    value = math.fsum(errors)/len(errors)
    require(math.isfinite(value), 'non-finite comparison MSE')
    return value


def rounded(value):
    require(math.isfinite(value) and -1 <= value <= 1, 'invalid projected weight')
    return int(math.copysign(math.floor(abs(value)+.5), value))


def integer_weights(weights):
    tables = {}
    for key, value in sorted(weights.items()):
        integer = rounded(value)
        if integer:
            phase, feature, code = key.split('/')
            tables.setdefault(phase, [{} for _ in range(64)])[int(feature)][code] = integer
    return tables


def artifact(weights, baseline, manifest_digest, seed):
    tables = integer_weights(weights)
    bounds = [max((abs(v) for fs in tables.values() for v in fs[i].values()), default=0)
              for i in range(64)]
    result = dict(format_version=2, score_contract=tr.SCORE_CONTRACT,
                  feature_contract=baseline['feature_contract'], weights=tables,
                  feature_max_abs=bounds, weight_digest=tr.digest(tables),
                  provenance=dict(trainer_version=tr.OPTIMIZER_COMPARISON_VERSION,
                                  input_manifest_digest=manifest_digest, seed=seed,
                                  licenses=baseline['provenance']['licenses'],
                                  optimizer=dict(name='project_adam_v1', normalization_divisor=64)))
    result['artifact_digest'] = tr.digest(result)
    tr.validate_artifact(result)
    return result


def initial(baseline, config):
    return dict(weights=flat(baseline['weights']), m={}, v={}, step=0,
                epoch=0, cursor=0, order=[], shuffle_seed=None, best_epoch=None,
                best_mse=None, stale=0, epochs=[], done=False,
                settings_digest=tr.digest(config), training_seconds=0.0)


def diagnostics(state, baseline, train, validation):
    weights = state['weights']
    base = flat(baseline['weights'])
    ints = flat(integer_weights(weights))
    keys = weights.keys() | base.keys()
    return dict(float_train_mse=metric(weights, train), float_validation_mse=metric(weights, validation),
                integer_train_mse=metric(ints, train), integer_validation_mse=metric(ints, validation),
                changed_weights=sum(weights.get(k, 0) != base.get(k, 0) for k in keys),
                nonzero_weights=sum(v != 0 for v in weights.values()),
                saturated_weights=sum(abs(v) == 1 for v in weights.values()),
                rounded_away_changes=sum(weights.get(k, 0) != base.get(k, 0)
                                         and ints.get(k, 0) == base.get(k, 0) for k in keys),
                phase_counts=dict(sorted(Counter(keys[0].split('/')[0] for keys, _ in train).items())))


def advance(previous, config, train, validation, baseline):
    """One completed batch, or a completed epoch boundary. No I/O or processes."""
    require(not previous['done'], 'optimizer already finished')
    state = copy.deepcopy(previous)
    require(state['settings_digest'] == tr.digest(config), 'changed optimizer settings')
    if not state['order']:
        state['epoch'] += 1
        # A fully specified per-epoch RNG replaces mutable hidden process state.
        state['shuffle_seed'] = int(tr.digest({'seed': config['seed'], 'epoch': state['epoch']})[:16], 16)
        state['order'] = list(range(len(train)))
        random.Random(state['shuffle_seed']).shuffle(state['order'])
    if state['cursor'] < len(train):
        indexes = state['order'][state['cursor']:state['cursor']+config['batch']]
        gradients = {}
        for index in indexes:
            keys, target = train[index]
            error = sum(state['weights'].get(key, 0) for key in keys)-target
            for key in keys:
                gradients[key] = gradients.get(key, 0.0) + 2*error/len(indexes)
        state['step'] += 1
        step = state['step']
        for key in sorted(gradients.keys() | state['m'].keys()):
            # Previously observed parameters retain Adam's momentum on a
            # zero-gradient batch; parameters never in teachers stay untouched.
            gradient = gradients.get(key, 0.0)
            m = config['beta1']*state['m'].get(key, 0)+(1-config['beta1'])*gradient
            v = config['beta2']*state['v'].get(key, 0)+(1-config['beta2'])*gradient*gradient
            update = config['learning_rate']*(m/(1-config['beta1']**step))/(math.sqrt(v/(1-config['beta2']**step))+config['epsilon'])
            require(all(math.isfinite(n) for n in (gradient, m, v, update)), 'non-finite Adam state')
            state['weights'][key] = max(-1., min(1., state['weights'].get(key, 0)-update))
            state['m'][key], state['v'][key] = m, v
        state['cursor'] += len(indexes)
    else:
        report = diagnostics(state, baseline, train, validation)
        report['epoch'] = state['epoch']
        state['epochs'].append(report)
        mse = report['integer_validation_mse']
        if state['best_mse'] is None or mse < state['best_mse']:
            state['best_epoch'], state['best_mse'], state['stale'] = state['epoch'], mse, 0
        else:
            state['stale'] += 1
        state['done'] = state['epoch'] >= config['epochs'] or state['stale'] >= config['patience']
        state['order'], state['cursor'] = [], 0
    return state
