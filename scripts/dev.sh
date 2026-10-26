#!/usr/bin/env bash
# Start the mock ERP, the backend and the frontend together. Ctrl-C stops all three.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/backend/data"

trap 'kill 0' EXIT

python3 "$ROOT/mock_po_api.py" 8080 "$ROOT/backend/data/erp_orders.json" &
(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --port 8000 --reload) &
(cd "$ROOT/frontend" && npm run dev -- --strictPort) &

wait
