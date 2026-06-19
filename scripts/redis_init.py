#!/usr/bin/env python3
"""
JARVIS OS — Redis memory init
Called by jarvis.sh on start: python3 scripts/redis_init.py
"""
import sys
import os

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_DIR)

try:
    from memory.redis_memory import write_state, write_task, reset_loop, ping

    if not ping():
        print("[REDIS] WARNING: Redis not reachable, skipping init")
        sys.exit(0)

    write_state(
        identity="JARVIS",
        task="booting",
        tools={},
        confidence="low",
        notes="startup"
    )
    
    write_task("idle")
    reset_loop()
    print("[REDIS] Agent memory initialised")

except Exception as e:
    print(f"[REDIS] Init failed (non-fatal): {e}")
    sys.exit(0)
