#!/usr/bin/env bash
# Starts the Indian Market Dashboard and keeps it running forever.
# Usage: bash run.sh

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$SCRIPT_DIR/venv"
APP="$SCRIPT_DIR/app.py"
PORT=8501
LOG="$SCRIPT_DIR/dashboard.log"

cd "$SCRIPT_DIR"

echo "[$(date)] Starting Indian Market Dashboard on port $PORT" | tee -a "$LOG"

while true; do
    "$VENV/bin/streamlit" run "$APP" \
        --server.port "$PORT" \
        --server.address 0.0.0.0 \
        --server.headless true \
        --server.enableCORS false \
        --server.enableXsrfProtection false \
        --browser.gatherUsageStats false \
        >> "$LOG" 2>&1

    echo "[$(date)] App crashed or exited. Restarting in 5s..." | tee -a "$LOG"
    sleep 5
done
