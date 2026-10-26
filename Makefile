VENV := backend/.venv

.PHONY: setup dev test lint gen-api results

setup:  ## Create the Python venv and install backend + frontend dependencies
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r backend/requirements-dev.txt
	cd frontend && npm install
	@test -f .env || (cp .env.example .env && echo "Created .env; add your OPENAI_API_KEY")

dev:    ## Run mock ERP (:8080), backend (:8000) and frontend (:5173)
	./scripts/dev.sh

test:   ## Backend (pytest) and frontend (vitest) tests; no network needed
	cd backend && .venv/bin/pytest -q
	cd frontend && npm test

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npm run lint && npx tsc -b

gen-api: ## Regenerate the frontend's TypeScript API types from the backend's OpenAPI schema
	cd frontend && npm run gen:api

results: ## All sample emails through the pipeline -> scripts/results.md (cached model output)
	$(VENV)/bin/python scripts/run_all.py --checks
