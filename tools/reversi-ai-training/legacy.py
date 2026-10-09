"""Isolated adapters for byte-frozen historical producers; never execute a runtime."""
import contextlib
import importlib.util
import sys
import hashlib
import json
from pathlib import Path

@contextlib.contextmanager
def producer(name, *, error_type=None, source_dir=None, source_digests=None):
    saved = {key: sys.modules.get(key) for key in ("training", "reinforcement", "random_inputs")}
    error_type = error_type or (saved["training"].TrainingError if saved["training"] is not None else ValueError)
    modules = {}
    directory = Path(source_dir) if source_dir is not None else Path(__file__).parent / "legacy_offline"
    try:
        if source_dir is not None and (not isinstance(source_digests, dict) or set(source_digests) != {"training.py", "reinforcement.py", "random_inputs.py"}):
            raise error_type("original legacy source digests are required")
        pins = source_digests if source_dir is not None else json.loads((directory / "source-digests.json").read_text())
        for key in ("training", "reinforcement", "random_inputs"):
            if hashlib.sha256((directory / (key + ".py")).read_bytes()).hexdigest() != pins[key + ".py"]:
                raise error_type("frozen legacy source digest mismatch")
        for key in ("training", "reinforcement", "random_inputs"):
            path = directory / (key + ".py")
            spec = importlib.util.spec_from_file_location(key, path)
            module = importlib.util.module_from_spec(spec)
            sys.modules[key] = module
            spec.loader.exec_module(module)
            modules[key] = module
        yield modules[name]
    except (ValueError, OSError, KeyError, TypeError) as error:
        raise error_type(str(error)) from error
    finally:
        for key, module in saved.items():
            if module is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = module
