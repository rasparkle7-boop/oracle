#!/bin/bash
# Stop a local ORACLE server on port 8787.
PIDS=$(lsof -ti tcp:8787 2>/dev/null || true)
if [ -n "$PIDS" ]; then
  kill $PIDS 2>/dev/null || true
  echo "Stopped ORACLE on port 8787."
else
  echo "No ORACLE process found on port 8787."
fi
