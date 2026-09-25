PYTHON ?= python3
CARGO ?= cargo
ORACLE_TOOL := tools/reversi-ai-oracle/oracle.py
ORACLE_CORPUS := tools/reversi-ai-oracle/corpus.jsonl
ORACLE_GOLDEN := tools/reversi-ai-oracle/golden.jsonl
ORACLE_PROFILE ?= ci-smoke-v1
ORACLE_TIMEOUT ?= 300
ORACLE_MATCH_TIMEOUT ?= 60
ORACLE_MATCH_GAMES ?= 2
ORACLE_REPORT ?= /tmp/reversi-adventure-oracle-report.jsonl
ORACLE_MATCH_REPORT ?= /tmp/reversi-adventure-oracle-match.json
BENCHMARK_CORPUS := tools/reversi-ai-benchmark/positions-v1.jsonl
BENCHMARK_REFERENCE := tools/reversi-ai-benchmark/reference-v1.jsonl
BENCHMARK_COMPARATOR := tools/reversi-ai-benchmark/compare.py
BENCHMARK_BASELINE ?=
BENCHMARK_CANDIDATE ?=
BENCHMARK_REPORT ?= /tmp/reversi-adventure-search-comparison-v1.json
BENCHMARK_REPETITIONS ?= 5
BENCHMARK_TIME_LIMIT_MS ?= 300000
PATTERN_TRAINER := tools/reversi-ai-training/training.py
PATTERN_MANIFEST := tools/reversi-ai-training/fixtures/tiny-manifest.json
PATTERN_ARTIFACT ?= /tmp/reversi-adventure-pattern-artifact.json
PATTERN_REPORT ?= /tmp/reversi-adventure-pattern-report.json
REINFORCEMENT_TOOL := tools/reversi-ai-training/reinforcement.py
REINFORCEMENT_MANIFEST ?= /tmp/reversi-adventure-reinforcement-manifest.json
REINFORCEMENT_OUTPUT_DIR ?= /tmp/reversi-adventure-reinforcement
REINFORCEMENT_REGRET_REPORT ?= /tmp/reversi-adventure-reinforcement-regret.jsonl
REINFORCEMENT_BASELINE_ARTIFACT ?=
REINFORCEMENT_VALIDATION_INPUT ?=
REINFORCEMENT_VALIDATION_SOURCE ?= project-owned-validation-v1
REINFORCEMENT_CANDIDATE_EXECUTABLE ?=
REINFORCEMENT_SEED ?= 20260926
REINFORCEMENT_GAME_COUNT ?= 64
REINFORCEMENT_OPENING_PLIES ?= 6
REINFORCEMENT_DEPTH ?= 12
REINFORCEMENT_EXACT_EMPTY ?= 16
REINFORCEMENT_TIME_LIMIT_MS ?= 300000
REINFORCEMENT_NODE_LIMIT ?= 10000000
REINFORCEMENT_DECISION_TIMEOUT_SECONDS ?= 310
REINFORCEMENT_MAX_DECISIONS ?= 7680
AI_EVALUATOR ?= strategic
AI_OPENING_DEPTH ?= 3
AI_MIDGAME_DEPTH ?= 4
AI_ENDGAME_DEPTH ?= 6
AI_EXACT_SOLVER_EMPTY_SQUARES ?= 12
AI_MATCH_OPENING_DEPTH ?= 1
AI_MATCH_MIDGAME_DEPTH ?= 2
AI_MATCH_ENDGAME_DEPTH ?= 3
AI_BINARY ?= $(if $(CARGO_TARGET_DIR),$(CARGO_TARGET_DIR)/debug/reversi-ai-cli,target/debug/reversi-ai-cli)
AI_COMMAND := $(AI_BINARY) --evaluator $(AI_EVALUATOR) --opening-depth $(AI_OPENING_DEPTH) --midgame-depth $(AI_MIDGAME_DEPTH) --endgame-depth $(AI_ENDGAME_DEPTH) --exact-solver-empty-squares $(AI_EXACT_SOLVER_EMPTY_SQUARES)
AI_MATCH_COMMAND := $(AI_BINARY) --evaluator $(AI_EVALUATOR) --opening-depth $(AI_MATCH_OPENING_DEPTH) --midgame-depth $(AI_MATCH_MIDGAME_DEPTH) --endgame-depth $(AI_MATCH_ENDGAME_DEPTH) --exact-solver-empty-squares $(AI_EXACT_SOLVER_EMPTY_SQUARES)
AI_CALIBRATION_COMMAND := $(AI_BINARY) --evaluator strategic --profile strong-engine-hcap-v1

.PHONY: oracle-test oracle-verify oracle-golden oracle-match oracle-evaluate oracle-ci oracle-corpus oracle-calibration benchmark-oracle-setup benchmark-corpus benchmark-corpus-verify benchmark-reference benchmark-reference-verify benchmark-compare pattern-training-test pattern-training-fixture pattern-reinforcement-prepare pattern-reinforcement-run pattern-reinforcement-verify pattern-reinforcement-regret

pattern-training-test:
	$(PYTHON) -m unittest discover -s tools/reversi-ai-training/tests -p 'test_*.py'

pattern-training-fixture: pattern-training-test
	$(PYTHON) $(PATTERN_TRAINER) train --manifest $(PATTERN_MANIFEST) --artifact $(PATTERN_ARTIFACT) --report $(PATTERN_REPORT)
	$(PYTHON) $(PATTERN_TRAINER) validate --artifact $(PATTERN_ARTIFACT)

pattern-reinforcement-prepare:
	@test -n "$(REINFORCEMENT_BASELINE_ARTIFACT)" && test -n "$(REINFORCEMENT_VALIDATION_INPUT)" && test -n "$(REINFORCEMENT_CANDIDATE_EXECUTABLE)" || (echo "Set REINFORCEMENT_BASELINE_ARTIFACT, REINFORCEMENT_VALIDATION_INPUT, and REINFORCEMENT_CANDIDATE_EXECUTABLE" >&2; exit 2)
	$(PYTHON) $(REINFORCEMENT_TOOL) prepare --manifest "$(REINFORCEMENT_MANIFEST)" --baseline-artifact "$(REINFORCEMENT_BASELINE_ARTIFACT)" --candidate-executable "$(REINFORCEMENT_CANDIDATE_EXECUTABLE)" --validation-input "$(REINFORCEMENT_VALIDATION_INPUT)" --validation-source "$(REINFORCEMENT_VALIDATION_SOURCE)" --seed $(REINFORCEMENT_SEED) --game-count $(REINFORCEMENT_GAME_COUNT) --opening-plies $(REINFORCEMENT_OPENING_PLIES) --opening-depth $(REINFORCEMENT_DEPTH) --midgame-depth $(REINFORCEMENT_DEPTH) --endgame-depth $(REINFORCEMENT_DEPTH) --exact-solver-empty-squares $(REINFORCEMENT_EXACT_EMPTY) --time-limit-ms $(REINFORCEMENT_TIME_LIMIT_MS) --node-limit $(REINFORCEMENT_NODE_LIMIT) --decision-timeout-seconds $(REINFORCEMENT_DECISION_TIMEOUT_SECONDS) --max-decisions $(REINFORCEMENT_MAX_DECISIONS)

# This is a human-operated long-running command; it is never a test prerequisite.
pattern-reinforcement-run:
	$(PYTHON) $(REINFORCEMENT_TOOL) run --manifest "$(REINFORCEMENT_MANIFEST)" --output-dir "$(REINFORCEMENT_OUTPUT_DIR)"

pattern-reinforcement-verify:
	$(PYTHON) $(REINFORCEMENT_TOOL) verify --manifest "$(REINFORCEMENT_MANIFEST)" --output-dir "$(REINFORCEMENT_OUTPUT_DIR)"

pattern-reinforcement-regret: pattern-reinforcement-verify
	@candidate_command="$$($(PYTHON) $(REINFORCEMENT_TOOL) regret-command --manifest "$(REINFORCEMENT_MANIFEST)" --output-dir "$(REINFORCEMENT_OUTPUT_DIR)")" || exit; $(PYTHON) $(ORACLE_TOOL) analyze --corpus $(ORACLE_CORPUS) --output "$(REINFORCEMENT_REGRET_REPORT)" --profile strong-engine-hcap-v1 --timeout $(ORACLE_TIMEOUT) --candidate-command "$$candidate_command"

oracle-test:
	$(PYTHON) -m unittest discover -s tools/reversi-ai-oracle/tests -p 'test_*.py'

oracle-corpus:
	$(PYTHON) $(ORACLE_TOOL) generate-corpus --output $(ORACLE_CORPUS)

oracle-verify: oracle-test
	$(PYTHON) $(ORACLE_TOOL) verify --corpus $(ORACLE_CORPUS) --golden $(ORACLE_GOLDEN) --profile $(ORACLE_PROFILE) --timeout $(ORACLE_TIMEOUT)

oracle-golden:
	$(PYTHON) $(ORACLE_TOOL) generate-golden --corpus $(ORACLE_CORPUS) --output $(ORACLE_GOLDEN) --profile $(ORACLE_PROFILE) --timeout $(ORACLE_TIMEOUT)

oracle-match:
	$(CARGO) build -p reversi-ai --bin reversi-ai-cli
	$(PYTHON) $(ORACLE_TOOL) match --candidate-command "$(AI_MATCH_COMMAND)" --games $(ORACLE_MATCH_GAMES) --profile $(ORACLE_PROFILE) --timeout $(ORACLE_MATCH_TIMEOUT) --output $(ORACLE_MATCH_REPORT)

oracle-evaluate:
	$(CARGO) build -p reversi-ai --bin reversi-ai-cli
	$(PYTHON) $(ORACLE_TOOL) analyze --corpus $(ORACLE_CORPUS) --output $(ORACLE_REPORT) --profile $(ORACLE_PROFILE) --timeout $(ORACLE_TIMEOUT) --candidate-command "$(AI_COMMAND)"

oracle-ci: oracle-test
	$(CARGO) build -p reversi-ai --bin reversi-ai-cli
	$(PYTHON) $(ORACLE_TOOL) ci --corpus $(ORACLE_CORPUS) --golden $(ORACLE_GOLDEN) --profile $(ORACLE_PROFILE) --timeout $(ORACLE_TIMEOUT) --candidate-command "$(AI_MATCH_COMMAND)" --games $(ORACLE_MATCH_GAMES) --match-timeout $(ORACLE_MATCH_TIMEOUT) --match-output $(ORACLE_MATCH_REPORT)

oracle-calibration:
	$(CARGO) build -p reversi-ai --bin reversi-ai-cli
	$(PYTHON) $(ORACLE_TOOL) analyze --corpus $(ORACLE_CORPUS) --output $(ORACLE_REPORT) --profile strong-engine-hcap-v1 --timeout $(ORACLE_TIMEOUT) --candidate-command "$(AI_CALIBRATION_COMMAND)"
	$(PYTHON) $(ORACLE_TOOL) match --candidate-command "$(AI_CALIBRATION_COMMAND)" --games $(ORACLE_MATCH_GAMES) --profile strong-engine-hcap-v1 --timeout $(ORACLE_MATCH_TIMEOUT) --output $(ORACLE_MATCH_REPORT)

benchmark-oracle-setup:
	$(PYTHON) $(ORACLE_TOOL) setup-oracle --timeout $(ORACLE_TIMEOUT)

benchmark-corpus:
	$(PYTHON) $(ORACLE_TOOL) generate-benchmark-corpus --output $(BENCHMARK_CORPUS) --timeout $(ORACLE_TIMEOUT)

benchmark-corpus-verify:
	$(PYTHON) $(ORACLE_TOOL) verify-benchmark-corpus --corpus $(BENCHMARK_CORPUS)

benchmark-reference:
	$(PYTHON) $(ORACLE_TOOL) generate-benchmark-reference --corpus $(BENCHMARK_CORPUS) --output $(BENCHMARK_REFERENCE) --timeout $(ORACLE_TIMEOUT)

benchmark-reference-verify:
	$(PYTHON) $(ORACLE_TOOL) verify-benchmark-reference --corpus $(BENCHMARK_CORPUS) --report $(BENCHMARK_REFERENCE)

benchmark-compare:
	@test -n "$(BENCHMARK_BASELINE)" && test -n "$(BENCHMARK_CANDIDATE)" || (echo "BENCHMARK_BASELINE and BENCHMARK_CANDIDATE must name explicit release profiler binaries" >&2; exit 2)
	$(PYTHON) $(BENCHMARK_COMPARATOR) --baseline "$(BENCHMARK_BASELINE)" --candidate "$(BENCHMARK_CANDIDATE)" --corpus $(BENCHMARK_CORPUS) --output $(BENCHMARK_REPORT) --repetitions $(BENCHMARK_REPETITIONS) --time-limit-ms $(BENCHMARK_TIME_LIMIT_MS)
