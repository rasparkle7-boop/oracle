#!/bin/bash
set -e
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "Creating ORACLE virtual environment..."
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -q --upgrade pip
python -m pip install -q -r requirements.txt
if [ ! -f "data/oracle.sqlite3" ]; then
  echo "First run: bootstrapping the global fixture grid (2-4 minutes)..."
  python -m oracle.cli sync --history
fi
echo
echo "ORACLE is starting at http://127.0.0.1:8787"
echo "Press CTRL+C to stop."
echo
python -m oracle.cli serve
