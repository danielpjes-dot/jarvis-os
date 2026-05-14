#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/mnt/e/coding/jarvis-os"

cd "$PROJECT_DIR"
python3 "$PROJECT_DIR/scripts/orpheus_server.py" > /tmp/jarvis-orpheus.log 2>&1