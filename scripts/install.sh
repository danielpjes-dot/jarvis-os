#!/bin/bash
set -euo pipefail
TARGET_DIR="/mnt/e/coding/jarvis-os/scripts"
mkdir -p "$TARGET_DIR"
cp watcher.py "$TARGET_DIR/watcher.py"
cp watcher.sh "$TARGET_DIR/watcher.sh"
chmod +x "$TARGET_DIR/watcher.py" "$TARGET_DIR/watcher.sh"
echo "Installed to $TARGET_DIR"
