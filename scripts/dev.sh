#!/usr/bin/env bash
# Start the mock ERP, the backend and the frontend together. Ctrl-C stops all three.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$ROOT/backend/data"

trap 'kill 0' EXIT

python3 "$ROOT/mock_po_api.py" 8080 "$ROOT/backend/data/erp_orders.json" &
# Open browser tabs hold the live-update stream (SSE) forever; without a graceful-shutdown
# timeout every --reload would wait for them and hang.
(cd "$ROOT/backend" && .venv/bin/uvicorn app.main:app --port 8000 --reload --timeout-graceful-shutdown 2) &
(cd "$ROOT/frontend" && npm run dev -- --strictPort) &

wait
