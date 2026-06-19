#!/usr/bin/env bash
set -euo pipefail

BASE="/mnt/e/coding/jarvis-os"
LOGDIR="/tmp/jarvis"

mkdir -p "$LOGDIR"

run_forever() {
  local name="$1"
  shift

  while true; do
    echo "[$name] starting"

    "$@" >> "$LOGDIR/$name.log" 2>&1

    rc=$?
    echo "[$name] exited rc=$rc restarting in 2s"

    sleep 2
  done
}

run_forever task_loop \
  python3 "$BASE/scripts/task_loop.py" &

run_forever telegram_loop \
  python3 "$BASE/scripts/telegram_watcher.py" &

run_forever telegram_debug \
  python3 "$BASE/scripts/telegram_debug_tail.py" &

wait