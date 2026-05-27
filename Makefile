.PHONY: install patch data pilot full clean help

help:
	@echo "SCRIBE — Makefile targets:"
	@echo "  make install   # npm + pip dependencies"
	@echo "  make patch     # apply pi-ai env-api-keys patch (fireworks/baseten)"
	@echo "  make data      # download DABStep context files via HuggingFace"
	@echo "  make pilot     # 5-task sanity pilot (~5 min, <$$1)"
	@echo "  make typecheck # TypeScript typecheck"
	@echo "  make clean     # remove node_modules + result sessions"

install:
	npm install
	python3 -m pip install -r requirements.txt

patch:
	node scripts/patch_pi_ai_env.cjs

data:
	python3 scripts/fetch_dabstep_data.py

typecheck:
	npx tsc --noEmit

pilot: install patch data
	bash scripts/repro.sh

clean:
	rm -rf node_modules
	find results -type d -name sessions -exec rm -rf {} + 2>/dev/null || true
	find results -type d -name specs -exec rm -rf {} + 2>/dev/null || true
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
