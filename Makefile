VENV := backend/.venv

.PHONY: setup dev test lint

setup:  ## Create the Python venv and install backend + frontend dependencies
	python3 -m venv $(VENV)
	$(VENV)/bin/pip install -q -r backend/requirements-dev.txt
	cd frontend && npm install
	@test -f .env || (cp .env.example .env && echo "Created .env; add your OPENAI_API_KEY")

dev:    ## Run mock ERP (:8080), backend (:8000) and frontend (:5173)
	./scripts/dev.sh

test:
	cd backend && .venv/bin/pytest -q

lint:
	cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check .
	cd frontend && npm run lint && npx tsc -b
