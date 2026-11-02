"""0054-only replay of historical executable identities and verified Oracle source."""
from __future__ import annotations

import re
import tempfile
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
    manifest = training.read_json(Path(source_manifest_path))
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
                     and isinstance(runtime.get("binary"), dict),
                     "invalid historical Oracle binary identity")
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


def historical_executable_pins(source_manifest_path: Path, comparison_root: Path | None = None,
                               evaluation_root: Path | None = None) -> dict:
    """Collect only executable identities named by the historical manifests."""
    manifest = training.read_json(Path(source_manifest_path))
    entries = [manifest["oracle_binary"]]
    if "candidate_executable" in manifest:
        entries.append(manifest["candidate_executable"])
    if "input_bundle" in manifest:
        bundle_pin = manifest["input_bundle"]
        bundle_path = Path(bundle_pin["path"])
        cycle.require(training.sha256_file(bundle_path) == bundle_pin["sha256"],
                      "historical input bundle changed")
        entries.append(training.read_json(bundle_path)["cli"]["binary"])
    # 0052/0053 executable pins are checked in their own settings context.
    # A later build can reuse the same path with a different digest from 0019.
    result = {}
    for entry in entries:
        cycle.require(isinstance(entry, dict) and set(entry) == {"path", "sha256"}
                      and isinstance(entry["path"], str) and Path(entry["path"]).is_absolute()
                      and isinstance(entry["sha256"], str)
                      and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is not None,
                      "invalid historical executable identity")
        path = str(Path(entry["path"]).resolve())
        normalized = {"path": path, "sha256": entry["sha256"]}
        cycle.require(path not in result or result[path] == normalized,
                      "conflicting historical executable identities")
        result[path] = normalized
    return result


@contextmanager
def historical_replay(source_manifest_path: Path, runtime_receipt_path: Path,
                      expected_identity: dict | None = None, *,
                      comparison_root: Path | None = None, evaluation_root: Path | None = None):
    """Replay old receipts with recorded executable pins after Oracle verification.

    The scoped adapter changes no historical manifest or validator default. It lets
    only 0054 replay code compare recorded executable entries while the independently
    verified runtime identity is saved in the new table32 manifest.
    """
    identity = verify_source_identity(source_manifest_path, runtime_receipt_path)
    if expected_identity is not None:
        cycle.require(identity == expected_identity,
                         "verified Oracle source identity differs from the table32 manifest")

    import input_bundle
    import optimizer_compare_matches as matches

    executable_pins = historical_executable_pins(source_manifest_path, comparison_root, evaluation_root)
    match_settings = [training.read_json(Path(root) / "manifest.json").get("matches", {})
                      for root in (comparison_root, evaluation_root) if root is not None]
    if len(match_settings) == 2:
        for key in ("candidate_executable", "oracle_binary"):
            if key in match_settings[0] and key in match_settings[1]:
                cycle.require(match_settings[0][key] == match_settings[1][key],
                              f"historical evaluation {key} differs from comparison")
    original_sha256_file = training.sha256_file
    original_file_entry = cycle.file_entry
    original_checked_pin = input_bundle.checked_pin
    original_request_inputs = input_bundle.request_inputs
    original_validate_settings = matches.validate_settings

    def source_verified_sha256_file(path):
        entry = executable_pins.get(str(Path(path).resolve()))
        return entry["sha256"] if entry else original_sha256_file(path)

    def source_verified_file_entry(path):
        entry = executable_pins.get(str(Path(path).resolve()))
        return dict(entry) if entry else original_file_entry(path)

    def source_verified_checked_pin(value, base):
        if isinstance(value, dict) and set(value) == {"path", "sha256"} and isinstance(value["path"], str):
            path = (base / value["path"]).resolve()
            entry = executable_pins.get(str(path))
            if entry is not None and value["sha256"] == entry["sha256"]:
                return path
        return original_checked_pin(value, base)

    def source_verified_request_inputs(stage, request):
        # request_inputs validates all stage fields and expands directory inputs.
        # Substitute only missing historical executable arguments while it does so;
        # return the recorded paths for its subsequent frozen-input comparison.
        if not isinstance(request, dict):
            return original_request_inputs(stage, request)
        replacements = {}
        adjusted = dict(request)
        for name in ("cli", "binary"):
            value = request.get(name)
            if not isinstance(value, str) or not Path(value).is_absolute():
                continue
            path = Path(value).resolve()
            if str(path) not in executable_pins or path.is_file():
                continue
            placeholder = Path(temporary) / str(len(replacements))
            placeholder.touch()
            replacements[placeholder] = Path(value)
            adjusted[name] = str(placeholder)
        return [replacements.get(path, path) for path in original_request_inputs(stage, adjusted)]

    def recorded_validate_settings(context, settings):
        if not any(settings == saved for saved in match_settings):
            return original_validate_settings(context, settings)
        pins = {}
        for key in ("candidate_executable", "oracle_binary"):
            entry = settings[key]
            cycle.require(isinstance(entry, dict) and set(entry) == {"path", "sha256"}
                          and isinstance(entry["path"], str) and Path(entry["path"]).is_absolute()
                          and isinstance(entry["sha256"], str)
                          and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]) is not None,
                          "invalid historical match executable identity")
            path = str(Path(entry["path"]).resolve())
            normalized = {"path": path, "sha256": entry["sha256"]}
            cycle.require(path not in pins or pins[path] == normalized,
                          "conflicting historical match executable identities")
            pins[path] = normalized

        def match_file_entry(path):
            entry = pins.get(str(Path(path).resolve()))
            return dict(entry) if entry else source_verified_file_entry(path)

        with mock.patch.object(cycle, "file_entry", match_file_entry):
            return original_validate_settings(context, settings)

    with tempfile.TemporaryDirectory(prefix="table32-historical-inputs-") as temporary, \
         mock.patch.object(training, "sha256_file", source_verified_sha256_file), \
         mock.patch.object(cycle, "file_entry", source_verified_file_entry), \
         mock.patch.object(input_bundle, "checked_pin", source_verified_checked_pin), \
         mock.patch.object(input_bundle, "request_inputs", source_verified_request_inputs), \
         mock.patch.object(matches, "validate_settings", recorded_validate_settings):
        yield identity
