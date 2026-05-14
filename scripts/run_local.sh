#!/usr/bin/env bash
# Boot the AI Budtender locally: backend (uvicorn) + frontend (python http.server).
# Cleans up both processes on Ctrl-C or script exit.
#
# Usage:
#   ./scripts/run_local.sh                # default ports 8000 + 3000
#   ./scripts/run_local.sh 8001 3001      # custom ports
#
# Env:
#   OPENAI_API_KEY must be set (read from .env via backend.config.load_dotenv)
#   for /chat to work. /health and /products work without it.

set -euo pipefail

BACKEND_PORT="${1:-8000}"
FRONTEND_PORT="${2:-3000}"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [ ! -d venv ]; then
  echo "ERROR: venv/ not found. Run: python3.12 -m venv venv && pip install -r backend/requirements.txt"
  exit 1
fi

if [ ! -f data/products.db ]; then
  echo "ERROR: data/products.db not found. Run:"
  echo "  venv/bin/python scripts/setup_db.py"
  echo "  venv/bin/python scripts/migrate_csv_to_sqlite.py"
  echo "  venv/bin/python scripts/seed_sale_data.py"
  exit 1
fi

# Verify sale data is seeded (M1 acceptance — required for AI Pick to show sale reasons)
SALE_COUNT=$(venv/bin/python -c "
import sqlite3
c = sqlite3.connect('data/products.db')
print(c.execute('SELECT COUNT(*) FROM products WHERE is_on_sale=1').fetchone()[0])
")
if [ "$SALE_COUNT" -lt 1 ]; then
  echo "WARNING: no sale data found (is_on_sale=0 for all rows)."
  echo "Run: venv/bin/python scripts/seed_sale_data.py"
fi

cleanup() {
  echo ""
  echo "Stopping servers..."
  [ -n "${BACKEND_PID:-}" ] && kill "$BACKEND_PID" 2>/dev/null || true
  [ -n "${FRONTEND_PID:-}" ] && kill "$FRONTEND_PID" 2>/dev/null || true
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "[1/2] Starting backend on :$BACKEND_PORT ..."
venv/bin/python -m uvicorn backend.main:app --port "$BACKEND_PORT" --host 0.0.0.0 &
BACKEND_PID=$!

# Wait for backend to be healthy
for i in 1 2 3 4 5 6 7 8 9 10; do
  if curl -sf "http://localhost:$BACKEND_PORT/health" >/dev/null 2>&1; then
    echo "      backend ready"
    break
  fi
  sleep 1
done

echo "[2/2] Starting frontend on :$FRONTEND_PORT ..."
venv/bin/python -m http.server "$FRONTEND_PORT" --directory frontend/ >/dev/null 2>&1 &
FRONTEND_PID=$!
sleep 1

echo ""
echo "======================================================"
echo "  AI Budtender running locally"
echo "  Backend:   http://localhost:$BACKEND_PORT"
echo "  Frontend:  http://localhost:$FRONTEND_PORT"
echo "  Health:    http://localhost:$BACKEND_PORT/health"
echo "  Products:  http://localhost:$BACKEND_PORT/products"
echo ""
echo "  Sale-tagged products: $SALE_COUNT / 217"
echo ""
echo "  Open the frontend URL in your browser to test the 4 flows."
echo "  Run scripts/verify_flows.py in another terminal for HTTP self-test."
echo ""
echo "  Press Ctrl-C to stop both servers."
echo "======================================================"

# Block until interrupted
wait
