PY       := uv run python
HARBOR   := uv run harbor
MODEL    ?= anthropic:claude-sonnet-4-6
ATTEMPTS ?= 5
PAGE     ?= demo-pages/halden-cycles-scored
PORT     ?= 8080

# Plugins, agent env and .env cannot live in harbor-job.json, so they stay here.
# --ae is load-bearing: Harbor forwards ANTHROPIC_API_KEY but not the base URL,
# so a gateway-scoped key gets a 401 from api.anthropic.com.
HARBOR_ARGS := --config dataset/harbor-job.json \
	--plugin langsmith --pk dataset_name=site-builder-briefs-harbor \
	--env-file .env \
	--ae ANTHROPIC_BASE_URL="$$ANTHROPIC_BASE_URL" \
	--yes

.PHONY: help setup ui page judge judge-quick harbor attempts haiku oracle results \
        snapshot verify sync clean

help:
	@echo "  DEMO, in order"
	@echo "    make ui           act 1 — the chat UI on :8000            (model)"
	@echo "    make page         act 3 — serve the scored page to click  (free)"
	@echo "    make results      act 4 — print the last Harbor result    (free)"
	@echo ""
	@echo "  RUN THE EVALS"
	@echo "    make judge        traditional: 5 briefs, 5 evaluators     (model)"
	@echo "    make judge-quick  just the Halden brief, no judges        (model)"
	@echo "    make harbor       one Harbor trial on a LangSmith sandbox (model)"
	@echo "    make attempts     same, ATTEMPTS=$(ATTEMPTS) times — one run is not an estimate"
	@echo "    make haiku        same as harbor, on haiku, to compare tiers"
	@echo "    make oracle       the reference solution — proves 1.0 is reachable"
	@echo ""
	@echo "  MAINTENANCE"
	@echo "    make setup        deps + playwright + npm"
	@echo "    make snapshot     build/inspect the sandbox snapshot"
	@echo "    make verify       run the verifier against known artifacts (free)"
	@echo "    make sync         vendor _shared/functional.py into each task"

setup:
	uv sync
	$(PY) -m playwright install chromium
	@echo "\nNow: cp .env.example .env and add LANGSMITH_API_KEY"

# ---- demo ---------------------------------------------------------------
ui:
	uv run uvicorn server:app --reload --port 8000

page:
	./serve.sh $(PAGE) $(PORT)

results:
	@$(PY) scripts/show_result.py

# ---- evals --------------------------------------------------------------
judge:
	$(PY) traditional/run_eval.py --run --model $(MODEL)

judge-quick:
	$(PY) traditional/run_eval.py --run --limit 1 --no-judges --model $(MODEL)

harbor: sync
	$(HARBOR) run $(HARBOR_ARGS)

attempts: sync
	$(HARBOR) run $(HARBOR_ARGS) -k $(ATTEMPTS) -n 2

haiku: sync
	$(HARBOR) run $(HARBOR_ARGS) --model anthropic:claude-haiku-4-5-20251001

oracle: sync
	$(HARBOR) run --config dataset/harbor-job.json --agent oracle --env-file .env --yes

# ---- maintenance --------------------------------------------------------
snapshot:
	@$(PY) build_snapshot.py --list
	@$(PY) build_snapshot.py

verify:
	@$(PY) scripts/verify.py

sync:
	@$(PY) dataset/sync.py

clean:
	rm -rf /tmp/harbor-jobs site/dist
