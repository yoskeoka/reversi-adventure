"""0054-only replay adapter for a rebuilt Oracle from the pinned source."""
from __future__ import annotations

import re
from contextlib import contextmanager
from pathlib import Path
from unittest import mock

import production_cycle as cycle
import table32_players as players
import training

POLICY = "source-archive-verified-v1"


def verify_source_identity(source_manifest_path: Path, runtime_receipt_path: Path) -> dict:
    """Validate the current runtime against 0019's source identity, not its old binary hash."""
    source_manifest_path = Path(source_manifest_path).resolve(strict=True)
    runtime_receipt_path = Path(runtime_receipt_path).resolve(strict=True)
    manifest = training.read_json(source_manifest_path)
    receipt = players.oracle.verify_runtime_receipt(runtime_receipt_path)

    cycle.require(manifest.get("oracle_version") == players.oracle.ORACLE_VERSION
                     and manifest.get("oracle_source_sha256") == players.oracle.SOURCE_SHA256,
                     "0019 Oracle source identity differs from the pinned version/archive")
    profile = players.oracle.profile_metadata(cycle.ORACLE_PROFILE)
    cycle.require(manifest.get("oracle_profile_id") == cycle.ORACLE_PROFILE.name
                     and manifest.get("oracle_profile") == profile
                     and manifest.get("oracle_exact_solver_empty_squares")
                         == players.oracle.profile_exact_threshold(cycle.ORACLE_PROFILE),
                     "0019 Oracle profile identity mismatch")
    cycle.require(receipt.get("oracle_version") == manifest["oracle_version"]
                     and receipt.get("source_archive", {}).get("sha256")
                         == manifest["oracle_source_sha256"],
                     "Oracle runtime receipt does not match the 0019 source identity")

    historical_binary = manifest.get("oracle_binary")
    runtime = receipt.get("runtime")
    cycle.require(isinstance(historical_binary, dict)
                     and set(historical_binary) == {"path", "sha256"}
                     and isinstance(historical_binary.get("path"), str)
                     and Path(historical_binary["path"]).is_absolute()
                     and isinstance(historical_binary.get("sha256"), str)
                     and re.fullmatch(r"[0-9a-f]{64}", historical_binary["sha256"]) is not None
                     and isinstance(runtime, dict)
                     and isinstance(runtime.get("binary"), dict)
                     and Path(historical_binary["path"]).resolve(strict=True)
                         == Path(runtime["binary"]["path"]).resolve(strict=True),
                     "Oracle runtime receipt binary path differs from the historical manifest")
    cycle.require(players.oracle.runtime_identity(
                         Path(runtime["binary"]["path"]), Path(runtime["working_directory"])) == runtime,
                     "prepared Oracle runtime changed")

    return {
        "policy": POLICY,
        "historical_binary": historical_binary,
        "oracle_version": manifest["oracle_version"],
        "source_archive_sha256": manifest["oracle_source_sha256"],
        "historical_profile_id": manifest["oracle_profile_id"],
        "runtime": runtime,
    }


@contextmanager
def historical_replay(source_manifest_path: Path, runtime_receipt_path: Path,
                      expected_identity: dict | None = None):
    """Replay old receipts with their recorded Oracle pin after source/runtime verification.

    The scoped adapter changes no historical manifest or validator default. It lets
    only 0054 replay code compare the recorded Oracle entry while the independently
    verified runtime identity is saved in the new table32 manifest.
    """
    identity = verify_source_identity(source_manifest_path, runtime_receipt_path)
    if expected_identity is not None:
        cycle.require(identity == expected_identity,
                         "verified Oracle source identity differs from the table32 manifest")

    historical_binary = identity["historical_binary"]
    oracle_path = Path(historical_binary["path"]).resolve(strict=True)
    original_sha256_file = training.sha256_file
    original_file_entry = cycle.file_entry

    def source_verified_sha256_file(path):
        resolved = Path(path).resolve()
        actual = original_sha256_file(path)
        if resolved == oracle_path:
            return historical_binary["sha256"]
        return actual

    def source_verified_file_entry(path):
        entry = original_file_entry(path)
        if Path(entry["path"]).resolve() == oracle_path:
            return historical_binary
        return entry

    with mock.patch.object(training, "sha256_file", source_verified_sha256_file), \
         mock.patch.object(cycle, "file_entry", source_verified_file_entry):
        try:
            yield identity
        finally:
            cycle.require(players.oracle.runtime_identity(
                              Path(identity["runtime"]["binary"]["path"]),
                              Path(identity["runtime"]["working_directory"])) == identity["runtime"],
                          "prepared Oracle runtime changed during historical replay")
