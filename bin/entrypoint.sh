#!/usr/bin/env bash
set -euo pipefail

python3 -m worker.main &
WORKER_PID=$!

node /app/server/dist/index.js &
SERVER_PID=$!

wait -n $WORKER_PID $SERVER_PID
EXIT_CODE=$?

kill $WORKER_PID $SERVER_PID 2>/dev/null || true
exit $EXIT_CODE
