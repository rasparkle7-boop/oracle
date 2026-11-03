#!/bin/bash
# ORACLE development server: backend auto-reloads on save.
set -e
cd "$(dirname "$0")"
if [ -d ".venv" ]; then
  source .venv/bin/activate
elif [ -d "../.venv" ]; then
  source ../.venv/bin/activate
else
  echo "No virtualenv found. Run ./run.command once first."
  exit 1
fi
echo "ORACLE dev server: http://127.0.0.1:8787 (auto-reload ON · browser live reload ON)"
export ORACLE_DEV_RELOAD=1
python -m uvicorn oracle.api:app --reload --reload-dir oracle --host 127.0.0.1 --port 8787
