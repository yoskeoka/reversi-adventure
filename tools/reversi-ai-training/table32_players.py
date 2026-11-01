"""Explicit project teacher/candidate and diagnostic-only full-solve adapters."""
from __future__ import annotations

import queue
import subprocess
import threading
import time
from pathlib import Path

import pilot
import reinforcement as rf
import table32_inputs as inputs
import table32_store as st

oracle = pilot.oracle


def full_solve_profile():
    name = "table32-full-solve-v1"
    profile = oracle.OracleProfile(name, 25,
        tuple(oracle.DepthProbabilityRange(move, move, 61 - move, "100")
              for move in range(1, 61)), 11, 25)
    # The extension lives only in this isolated tooling entry point; historical
    # Oracle producers and their source digests remain unchanged.
    oracle.PROFILES[name] = profile
    oracle.validate_profile(profile)
    return profile


def player_argv(executable,artifact,config,evaluator):
    argv=[str(executable),"--evaluator",evaluator,"--trained-artifact",str(artifact)]
    for key in ("opening_depth","midgame_depth","endgame_depth",
                "exact_solver_empty_squares","time_limit_ms","node_limit"):
        argv += ["--"+key.replace("_","-"),str(config[key])]
    return argv+["--exact-cache-scope","turn"]


def validate_raw_decision(identifier, board, side, result, config, *, expected_pins=None,
                          expected_evaluator="trained"):
    raw = result.get("raw", {})
    if expected_pins is not None:
        st.require(raw.get("pins_before") == expected_pins and raw.get("pins_after") == expected_pins,
                   "candidate executable/artifact live pins differ")
    elif "pins_before" in raw or "pins_after" in raw:
        st.require(raw.get("pins_before") == raw.get("pins_after"), "candidate live pins changed")
    if result.get("forced_pass") is True:
        expected = {"move": "pass", "score": 0, "completed_depth": 0,
                    "exact": False, "nodes": 0, "elapsed_ms": 0,
                    "forced_pass": True,
                    "raw": {"forced_pass": {"board": board, "side": side,
                                             "reason": "no-legal-move"}}}
        if "pins_before" in raw:
            expected["raw"].update(pins_before=raw["pins_before"], pins_after=raw["pins_after"])
        st.require(result.get("board", board) == board and result.get("side", side) == side,
                   "forced-pass state differs")
        decision = {key: value for key, value in result.items() if key not in ("board", "side", "player")}
        st.require(st.blob(decision) == st.blob(expected), "forced-pass evidence differs")
        inputs.validate_decision(board, side, result, config)
        return result
    if expected_pins is not None:
        st.require(raw.get("argv")==player_argv(expected_pins["executable"]["path"],
            expected_pins["artifact"]["path"],config,expected_evaluator),"candidate search argv differs")
    st.require(raw.get("request") == f"{identifier}\t{board}\t{side}"
               and raw.get("stdout") == f"{identifier}\t{result.get('move')}\n",
               "candidate raw request/response mismatch")
    st.require(raw.get("reset") == {"request": f"new_game\t{identifier}",
                                    "stdout": f"new_game\t{identifier}\tready\n"},
               "candidate reset evidence differs")
    line = raw.get("stderr", "")
    fields = diagnostic_fields(line)
    st.require(fields.get("position_id") == identifier and fields.get("outcome") in ("move", "pass"),
               "candidate telemetry identity mismatch")
    expected = {"move": result["move"], "score": int(fields["score"]),
                "completed_depth": int(fields["completed_depth"]),
                "exact": fields["exact"] == "true", "nodes": int(fields["nodes"]),
                "elapsed_ms": (int(fields["elapsed_us"]) + 999) // 1000}
    st.require(fields["exact"] in ("true", "false")
               and all(result.get(key) == value for key, value in expected.items()),
               "candidate telemetry differs from raw evidence")
    inputs.validate_decision(board, side, result, config)
    return result


def diagnostic_fields(line):
    st.require(isinstance(line, str) and line.startswith("search_diagnostic_v1\t"),
               "missing raw search telemetry")
    fields = {}
    for item in line.split("\t")[1:]:
        st.require("=" in item, "malformed raw search telemetry")
        key, value = item.split("=", 1)
        st.require(key and key not in fields, "duplicate raw search telemetry field")
        fields[key] = value
    st.require({"position_id", "outcome", "score", "completed_depth", "exact", "nodes", "elapsed_us"} <= set(fields),
               "incomplete raw search telemetry")
    try:
        for key in ("score", "completed_depth", "nodes", "elapsed_us"):
            int(fields[key])
    except ValueError:
        st.require(False, "incomplete or invalid raw search telemetry score/numeric field")
    st.require(all(int(fields[key]) >= 0 for key in ("completed_depth", "nodes", "elapsed_us")),
               "negative raw search telemetry field")
    st.require(fields["exact"] in ("true", "false"), "invalid raw search exactness")
    return fields


class Player(rf.Candidate):
    """Reuse the protocol transport with explicit evaluator and saved raw bytes."""
    def __init__(self, executable, artifact, config, timeout, *, evaluator="trained", log=None,
                 expected_pins=None):
        self.expected_pins = expected_pins
        if expected_pins is not None:
            st.require(set(expected_pins) == {"executable", "artifact"}
                       and Path(expected_pins["executable"]["path"]).resolve() == Path(executable).resolve()
                       and Path(expected_pins["artifact"]["path"]).resolve() == Path(artifact).resolve(),
                       "candidate live pin paths differ")
            self._check_live_pins()
        argv = player_argv(executable,artifact,config,evaluator)
        self.evaluator=evaluator
        self.log, self.log_lock, self.argv = Path(log) if log else None, threading.Lock(), argv
        self.process = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, bufsize=0)
        self.timeout, self.buffer, self.diagnostics = timeout, bytearray(), True
        self.diagnostic_lines = queue.Queue()
        self.diagnostic_reader = threading.Thread(target=self._read_diagnostics, daemon=True)
        self.diagnostic_reader.start()
        self.config = config
        try:
            self._check_live_pins()
        except Exception:
            self.close()
            raise

    def _check_live_pins(self):
        pins = getattr(self, "expected_pins", None)
        if pins is not None:
            for value in pins.values():
                st.check_pin(value)
            return {name: dict(value) for name, value in pins.items()}
        return None

    def _save(self, value):
        if self.log:
            with self.log_lock, self.log.open("ab") as stream:
                stream.write(st.blob(value))
                stream.flush()

    def _read_diagnostics(self):
        assert self.process.stderr is not None
        try:
            for line in iter(self.process.stderr.readline, b""):
                self._save({"argv": self.argv, "stream": "stderr", "bytes_hex": line.hex()})
                self.diagnostic_lines.put(line)
        finally:
            self.diagnostic_lines.put(None)

    def request(self, identifier, request):
        self._save({"argv": self.argv, "stream": "stdin", "request": request})
        try:
            answer = super().request(identifier, request)
        except Exception as error:
            self._save({"argv": self.argv, "request": request, "failure": str(error),
                        "stdout_partial_hex": bytes(self.buffer).hex(),
                        "returncode": self.process.poll()})
            raise
        self.last_request = {"request": request, "stdout": answer}
        self._save({"argv": self.argv, **self.last_request})
        return answer

    def decision(self, identifier, board, side):
        pins_before = self._check_live_pins()
        if not rf.legal_moves(board, side):
            st.require(bool(rf.legal_moves(board, rf.other(side))), "terminal position has no decision")
            result = {"move": "pass", "score": 0, "completed_depth": 0,
                      "exact": False, "nodes": 0, "elapsed_ms": 0,
                      "forced_pass": True,
                      "raw": {"forced_pass": {"board": board, "side": side,
                                               "reason": "no-legal-move"}}}
            if pins_before is not None:
                result["raw"].update(pins_before=pins_before,pins_after=self._check_live_pins())
            self._save(result)
            return validate_raw_decision(identifier, board, side, result, self.config,
                                         expected_pins=getattr(self,"expected_pins",None),
                                         expected_evaluator=getattr(self,"evaluator","trained"))
        self.new_game(identifier)
        reset = dict(self.last_request)
        move = self.choose(identifier, board, side)
        raw = dict(self.last_request)
        deadline = time.monotonic() + self.timeout
        while True:
            remaining = deadline - time.monotonic()
            st.require(remaining > 0, "candidate search diagnostic timed out")
            try:
                line = self.diagnostic_lines.get(timeout=remaining)
            except queue.Empty:
                st.require(False, "candidate search diagnostic timed out")
            st.require(line is not None, "candidate exited without diagnostic")
            try:
                line = line.decode("ascii").rstrip("\r\n")
            except UnicodeDecodeError:
                st.require(False, "candidate search diagnostic is not ASCII")
            if not line.startswith("search_diagnostic_v1\t"):
                continue
            raw.update(stderr=line, reset=reset, argv=self.argv)
            fields = diagnostic_fields(line)
            result = {"move": move, "score": int(fields["score"]),
                      "completed_depth": int(fields["completed_depth"]),
                      "exact": fields["exact"] == "true", "nodes": int(fields["nodes"]),
                      "elapsed_ms": (int(fields["elapsed_us"]) + 999) // 1000,
                      "raw": raw}
            if pins_before is not None:
                raw.update(pins_before=pins_before,pins_after=self._check_live_pins())
            self._save(result)
            return validate_raw_decision(identifier, board, side, result, self.config,
                                         expected_pins=getattr(self,"expected_pins",None),
                                         expected_evaluator=getattr(self,"evaluator","trained"))


def verify_query(query, saved, runtime, timeout):
    st.require(saved.get("query") == query, "full-solve query differs")
    board, side = query["board"], query["side"]
    if not rf.legal_moves(board, side) and not rf.legal_moves(board, rf.other(side)):
        expected = {"score": oracle.terminal_score(board, side), "exact": True,
                    "completed_depth": board.count(".")}
        st.require(saved.get("result") == expected and saved.get("raw") == {"terminal": True},
                   "terminal Oracle diagnostic differs")
        return saved
    effective, sign = oracle.effective_query(board, side)
    raw = saved["raw"]
    st.require(raw["runtime"] == runtime and raw["timeout"] == timeout
               and raw["runtime_before"] == runtime and raw["runtime_after"] == runtime
               and raw["returncode"] == 0 and raw["problem"] == oracle.to_egaroucid_problem(board, effective) + "\n",
               "Oracle raw identity differs")
    argv = oracle.oracle_argv(Path(runtime["binary"]["path"]), full_solve_profile(),
                              solve_path=Path(raw["problem_path"]), child_query=False)
    st.require(raw["argv"] == argv, "Oracle full-solve argv differs")
    result = oracle.parse_solve_output(raw["stdout"], [board.count(".")], full_solve_profile())[0]
    st.require(result["exact"] and result["move"] in rf.legal_moves(board, effective),
               "Oracle full solve incomplete or illegal")
    expected = {"score": sign * result["value"], "exact": True,
                "completed_depth": result["completed_depth"]}
    st.require(saved["result"] == expected, "Oracle normalized score differs from raw")
    return saved


def query_oracle(query, runtime, timeout, attempt):
    board, side = query["board"], query["side"]
    if not rf.legal_moves(board, side) and not rf.legal_moves(board, rf.other(side)):
        saved = {"query": query, "result": {"score": oracle.terminal_score(board, side),
                 "exact": True, "completed_depth": board.count(".")}, "raw": {"terminal": True}}
    else:
        before = oracle.runtime_identity(Path(runtime["binary"]["path"]),Path(runtime["working_directory"]))
        st.require(before == runtime, "Oracle runtime changed before full solve")
        effective, sign = oracle.effective_query(board, side)
        problem = oracle.to_egaroucid_problem(board, effective) + "\n"
        path = attempt / (query["id"] + ".problem.txt")
        path.write_text(problem)
        argv = oracle.oracle_argv(Path(runtime["binary"]["path"]), full_solve_profile(),
                                 solve_path=path, child_query=False)
        # The supervisor enforces the aggregate descendant RSS and cumulative
        # wall ceiling in addition to this per-query watchdog.
        try:
            response = subprocess.run(argv, cwd=runtime["working_directory"], timeout=timeout,
                                      capture_output=True, text=True)
        except (subprocess.TimeoutExpired, OSError) as error:
            stdout, stderr = getattr(error, "stdout", None), getattr(error, "stderr", None)
            def bytes_hex(value):
                return (value if isinstance(value, bytes) else (value or "").encode()).hex()
            raw = {"runtime": runtime, "timeout": timeout, "problem": problem,
                   "problem_path": str(path), "argv": argv, "failure": str(error),
                   "stdout_hex": bytes_hex(stdout), "stderr_hex": bytes_hex(stderr),
                   "returncode": None, "runtime_before": before}
            with (attempt / "oracle.jsonl").open("ab") as stream:
                stream.write(st.blob(raw))
                stream.flush()
            raise
        after_error = None
        try:
            after = oracle.runtime_identity(Path(runtime["binary"]["path"]),Path(runtime["working_directory"]))
        except Exception as error:
            after, after_error = None, str(error)
        raw = {"runtime": runtime, "timeout": timeout, "problem": problem,
               "problem_path": str(path), "argv": argv, "stdout": response.stdout,
               "stderr": response.stderr, "returncode": response.returncode,
               "runtime_before": before, "runtime_after": after}
        if after_error is not None:
            raw["runtime_after_error"] = after_error
        with (attempt / "oracle.jsonl").open("ab") as stream:
            stream.write(st.blob(raw))
        st.require(after == runtime, "Oracle runtime changed during full solve")
        st.require(response.returncode == 0, "Oracle query failed")
        result = oracle.parse_solve_output(response.stdout, [board.count(".")], full_solve_profile())[0]
        saved = {"query": query, "raw": raw, "result": {
            "score": sign * result["value"], "exact": result["exact"],
            "completed_depth": result["completed_depth"]}}
    return verify_query(query, saved, runtime, timeout)
