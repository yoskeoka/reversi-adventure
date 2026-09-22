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
PATTERN_TRAINER := tools/reversi-ai-training/training.py
PATTERN_MANIFEST := tools/reversi-ai-training/fixtures/tiny-manifest.json
PATTERN_ARTIFACT ?= /tmp/reversi-adventure-pattern-artifact.json
PATTERN_REPORT ?= /tmp/reversi-adventure-pattern-report.json
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

.PHONY: oracle-test oracle-verify oracle-golden oracle-match oracle-evaluate oracle-ci oracle-corpus oracle-calibration pattern-training-test pattern-training-fixture

pattern-training-test:
	$(PYTHON) -m unittest discover -s tools/reversi-ai-training/tests -p 'test_*.py'

pattern-training-fixture: pattern-training-test
	$(PYTHON) $(PATTERN_TRAINER) train --manifest $(PATTERN_MANIFEST) --artifact $(PATTERN_ARTIFACT) --report $(PATTERN_REPORT)
	$(PYTHON) $(PATTERN_TRAINER) validate --artifact $(PATTERN_ARTIFACT)

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
