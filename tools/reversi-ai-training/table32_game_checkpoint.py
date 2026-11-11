"""Persist individual teacher decisions without changing completed game receipts."""
from pathlib import Path

import table32_inputs as inputs
import table32_store as st


class GameDecisions:
    def __init__(self, root, manifest, spec, choose, validate):
        self.folder = Path(root) / "generation-checkpoints" / st.digest(spec)
        self.manifest_digest = st.digest(manifest)
        self.spec = spec
        self.choose = choose
        self.validate = validate
        self.index = 0
        if self.folder.exists():
            paths = sorted(self.folder.glob("*.json"))
            st.require(all(path.name == f"{i:03d}.json" for i, path in enumerate(paths)),
                       "non-contiguous generation decision checkpoints")

    def __call__(self, identifier, board, side, settings):
        expected = {"manifest_digest": self.manifest_digest, "spec": self.spec,
                    "index": self.index, "identifier": identifier, "board": board,
                    "side": side, "settings": settings}
        path = self.folder / f"{self.index:03d}.json"
        if path.exists():
            saved = st.read(path)
            st.require(saved == st.seal(saved) and
                       all(saved.get(key) == value for key, value in expected.items()),
                       "generation decision checkpoint differs")
            decision = saved["decision"]
        else:
            decision = self.choose(identifier, board, side, settings)
        inputs.validate_decision(board, side, decision, settings)
        self.validate(identifier, board, side, decision, settings)
        if not path.exists():
            st.atomic(path, st.seal({**expected, "decision": decision}), once=True)
        self.index += 1
        return decision
