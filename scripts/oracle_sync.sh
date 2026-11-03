#!/bin/bash
# Cron-friendly headless cycle. Add with:
#   */30 * * * * /path/to/oracle/scripts/oracle_sync.sh >> /tmp/oracle_cron.log 2>&1
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
python -m oracle.cli sync
