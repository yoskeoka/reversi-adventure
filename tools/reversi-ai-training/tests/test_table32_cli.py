"""Frozen scale/seed controls at the operator entry point; no engine starts."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import table32
import table32_store as st
import table32_players as players
import table32_inputs as inputs
import production_cycle


class Table32CliTests(unittest.TestCase):
    def test_historical_match_exposure_includes_decisions_and_terminal_both_sides(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            self.assertEqual(table32.verified_match_exposure_keys(root),set())
            (root/"matches").mkdir()
            board,side=inputs.advance(inputs.rf.INITIAL,"B","d3")
            game={"start_board":inputs.rf.INITIAL,"start_side":"B",
                  "decisions":[{"board":board,"side":side}],"terminal_board":"B"*64}
            for name in ("games.jsonl","oracle-games.jsonl"):
                (root/"matches"/name).write_bytes(st.blob(game))
            self.assertEqual(table32.verified_match_exposure_keys(root),{
                inputs.position_key(inputs.rf.INITIAL,"B"),inputs.position_key(board,side),
                inputs.position_key("B"*64,"B"),inputs.position_key("B"*64,"W")})

    def test_interrupted_archive_publication_keeps_completed_output_and_can_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/"exposure-keys-20.jsonl"
            data=b'"completed-key"\n'
            with mock.patch.object(st.os,"replace",side_effect=KeyboardInterrupt):
                with self.assertRaises(KeyboardInterrupt):
                    st.atomic_bytes(path,data,once=True)
            self.assertFalse(path.exists())
            st.atomic_bytes(path,data,once=True)
            self.assertEqual(path.read_bytes(),data)
            with self.assertRaisesRegex(Exception,"immutable output differs"):
                st.atomic_bytes(path,b'"changed"\n',once=True)
            self.assertEqual(path.read_bytes(),data)

    def prepare_fixture(self,folder,extra):
        executable=folder/"fixture-cli"
        oracle_binary=folder/"fixture-oracle"
        receipt=folder/"fixture-runtime.json"
        executable.write_text("never executed")
        oracle_binary.write_text("fixture Oracle")
        runtime={"binary":{"path":str(oracle_binary.resolve()),
                            "sha256":table32.training.sha256_file(oracle_binary)},
                 "working_directory":str(folder.resolve()),"resources":[]}
        source_manifest=folder/"source.json"
        source_value={"oracle_version":players.oracle.ORACLE_VERSION,
                      "oracle_source_sha256":players.oracle.SOURCE_SHA256,
                      "oracle_profile_id":production_cycle.ORACLE_PROFILE.name,
                      "oracle_profile":players.oracle.profile_metadata(production_cycle.ORACLE_PROFILE),
                      "oracle_exact_solver_empty_squares":players.oracle.profile_exact_threshold(
                          production_cycle.ORACLE_PROFILE),
                      "oracle_binary":{"path":str(oracle_binary.resolve()),
                                       "sha256":table32.training.sha256_file(oracle_binary)}}
        source_manifest.write_text(json.dumps(source_value,sort_keys=True)+"\n")
        receipt_value={"version":players.oracle.RUNTIME_RECEIPT_VERSION,"status":"complete",
                       "oracle_version":players.oracle.ORACLE_VERSION,
                       "source_archive":{"path":str(folder/"source.tar.gz"),
                                          "sha256":players.oracle.SOURCE_SHA256},
                       "runtime":runtime}
        receipt.write_text(json.dumps(receipt_value,sort_keys=True)+"\n")
        argv=["prepare","--run-root",str(folder/"run"),"--source-manifest",str(folder/"source.json"),
              "--source-comparison-root",str(folder/"source52"),"--source-evaluation-root",str(folder/"source53"),
              "--candidate-executable",str(executable),"--oracle-runtime-receipt",str(receipt),*extra]
        identity={"policy":"source-archive-verified-v1",
                  "historical_binary":source_value["oracle_binary"],
                  "oracle_version":players.oracle.ORACLE_VERSION,
                  "source_archive_sha256":players.oracle.SOURCE_SHA256,
                  "historical_profile_id":production_cycle.ORACLE_PROFILE.name,
                  "runtime":runtime}
        originals={"fixture":True,"oracle_source_identity":identity,
                   "source_manifest":st.pin(source_manifest)}
        with mock.patch.object(table32,"clean_commit",return_value="a"*40), \
             mock.patch.object(table32,"historical",return_value=(originals,{"fixture":True})) as history, \
             mock.patch.object(players.oracle,"runtime_identity",return_value=runtime), \
             mock.patch.object(players.oracle,"verify_runtime_receipt",return_value=receipt_value), \
             mock.patch.object(table32.subprocess,"Popen",side_effect=AssertionError("unexpected engine")), \
             contextlib.redirect_stdout(io.StringIO()):
            table32.main(argv)
        return st.read(folder/"run/manifest.json"),history

    def test_scaled_prepare_freezes_independent_seed_and_every_budget(self):
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary)
            manifest,history=self.prepare_fixture(folder,["--seed","2026110202",
                "--train-per-prefix","24","--validation-per-prefix","4","--test-per-prefix","4",
                "--early-positions","512","--early-candidates-per-phase","64",
                "--max-steps","2000","--max-proposals","3000","--max-wall-seconds","400000"])
            self.assertEqual(manifest["seed"],2026110202)
            self.assertEqual(history.call_args.kwargs["seed"],2026110202)
            self.assertEqual(manifest["limits"]["games"],256)
            self.assertEqual(manifest["limits"]["early_labels"],512)
            self.assertEqual(manifest["limits"]["training_steps_per_phase"],2000)
            self.assertEqual(manifest["limits"]["export_proposals_per_phase"],3000)
            self.assertEqual(manifest["limits"]["wall_seconds"],400000)
            self.assertEqual({spec["seed"] for spec in manifest["generation_plan"]},{2026110202})
            with mock.patch.object(players.oracle,"verify_runtime_receipt",
                                   return_value=json.loads((folder/"fixture-runtime.json").read_text())), \
                 mock.patch.object(players.oracle,"runtime_identity",return_value=manifest["oracle_runtime"]):
                self.assertEqual(table32.load(folder/"run",verify_originals=False)[0],manifest)
            with self.assertRaisesRegex(Exception,"run root exists"):
                self.prepare_fixture(folder,["--seed","2026110203"])
            self.assertEqual(st.read(folder/"run/manifest.json"),manifest)

    def test_invalid_limits_and_seed_fail_before_historical_verification(self):
        for extra in (["--seed","-1"],["--train-per-prefix","0"],
                      ["--decision-timeout-seconds","311"]):
            with self.subTest(extra=extra),tempfile.TemporaryDirectory() as temporary:
                folder=Path(temporary)
                with mock.patch.object(table32,"historical",side_effect=AssertionError("must not verify")):
                    with self.assertRaises(Exception) as failure:
                        self.prepare_fixture(folder,extra)
                    self.assertNotIsInstance(failure.exception,AssertionError)
                self.assertFalse((folder/"run").exists())
