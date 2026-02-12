#!/usr/bin/env bash
set -e

echo "Waiting for PostgreSQL..."
until pg_isready -h db -U flutracker -q 2>/dev/null; do
  sleep 1
done
echo "PostgreSQL is ready."

# Start uvicorn in the background with a log file
echo "Starting FastAPI server on port 8000..."
nohup uvicorn backend.app.main:app \
  --host 0.0.0.0 \
  --port 8000 \
  --reload \
  --reload-dir backend \
  > /tmp/uvicorn.log 2>&1 &

# Wait briefly and verify it started
sleep 2
if curl -sf http://localhost:8000/ > /dev/null 2>&1; then
  echo "FastAPI server is running on http://localhost:8000"
else
  echo "FastAPI server starting (check /tmp/uvicorn.log for details)"
fi
