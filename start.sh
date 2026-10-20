#!/bin/bash
set -eo pipefail

echo "=========================================================="
echo " Starting SealAPI Lead Research Engine (Single Container) "
echo "=========================================================="

# Create directories if missing
mkdir -p /app/data/uploads /app/data/batches

# 1. Start Python FastAPI backend in the background (Port 8000)
echo "[Supervisor] Launching FastAPI research backend on port 8000..."
uvicorn src.lead_research.server:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait briefly for backend to initialize
for i in {1..15}; do
  if curl -s http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
    echo "[Supervisor] FastAPI backend is healthy and responding."
    break
  fi
  sleep 1
done

# 2. Start Next.js frontend standalone server (Port 3000)
echo "[Supervisor] Launching Next.js frontend server on port 3000..."
cd /app/frontend
PORT=3000 BACKEND_API_URL="http://127.0.0.1:8000" node server.js &
FRONTEND_PID=$!

# Graceful shutdown handler
cleanup() {
  echo "[Supervisor] Caught termination signal. Terminating child processes..."
  kill -TERM "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  wait "$BACKEND_PID" "$FRONTEND_PID" 2>/dev/null || true
  echo "[Supervisor] All processes exited. Container shutdown complete."
  exit 0
}

trap cleanup SIGTERM SIGINT

# Monitor both processes; if either dies, exit and trigger cleanup
wait -n "$BACKEND_PID" "$FRONTEND_PID"
EXIT_STATUS=$?
echo "[Supervisor] A process terminated unexpectedly with exit status $EXIT_STATUS."
cleanup
