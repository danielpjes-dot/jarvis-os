#!/usr/bin/env python3
"""
JARVIS OS — Redis session snapshot
Called by jarvis.sh on stop: python3 scripts/redis_snapshot.py
Saves session to $VAULT_DIR/snapshots/ before Redis is cleared.
"""
import sys
import os
import json
import pathlib
import datetime

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VAULT_DIR   = os.environ.get("VAULT_DIR", "/mnt/d/Jarvis_vault")
sys.path.insert(0, PROJECT_DIR)

try:
    from memory.redis_memory import snapshot, flush, ping

    if not ping():
        print("[REDIS] Not reachable, skipping snapshot")
        sys.exit(0)

    data = snapshot()

    # Only save if there's something meaningful
    has_content = (
        data.get("task") or
        data.get("steps") or
        data.get("working_memory")
    )

    if not has_content:
        print("[REDIS] Session empty, skipping snapshot")
        flush()
        sys.exit(0)

    out_dir = pathlib.Path(VAULT_DIR) / "snapshots"
    out_dir.mkdir(parents=True, exist_ok=True)

    fname = out_dir / f"session_{datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.json"
    fname.write_text(json.dumps(data, indent=2, ensure_ascii=False))

    flush()
    print(f"[REDIS] Snapshot saved: {fname.name}")
    print(f"[REDIS]   task:    {data.get('task', '-')}")
    print(f"[REDIS]   steps:   {len(data.get('steps', []))}")
    print(f"[REDIS]   memory:  {len(data.get('working_memory', []))}")
    print(f"[REDIS]   loops:   {data.get('loop_count', 0)}")

except Exception as e:
    print(f"[REDIS] Snapshot failed (non-fatal): {e}")
    sys.exit(0)
