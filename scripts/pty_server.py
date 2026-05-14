#!/usr/bin/env python3
import asyncio
import json
import os
import pty
import select
import signal
import subprocess
from pathlib import Path

import websockets

HOST = "127.0.0.1"
PORT = 4010
DEFAULT_CWD = "/mnt/e/coding/jarvis-os"


async def terminal_session(websocket):
    cwd = DEFAULT_CWD

    master_fd, slave_fd = pty.openpty()

    env = os.environ.copy()
    env["TERM"] = "xterm-256color"

    proc = subprocess.Popen(
        ["/bin/bash"],
        cwd=cwd,
        env=env,
        stdin=slave_fd,
        stdout=slave_fd,
        stderr=slave_fd,
        preexec_fn=os.setsid,
        close_fds=True,
    )

    os.close(slave_fd)

    async def read_pty():
        try:
            while True:
                if proc.poll() is not None:
                    await websocket.send(json.dumps({
                        "type": "exit",
                        "code": proc.returncode,
                    }))
                    break

                ready, _, _ = select.select([master_fd], [], [], 0.05)
                if ready:
                    try:
                        data = os.read(master_fd, 4096)
                    except OSError:
                        break

                    if data:
                        await websocket.send(json.dumps({
                            "type": "output",
                            "data": data.decode("utf-8", errors="replace"),
                        }))

                await asyncio.sleep(0.01)
        except Exception as e:
            try:
                await websocket.send(json.dumps({
                    "type": "error",
                    "error": str(e),
                }))
            except Exception:
                pass

    reader_task = asyncio.create_task(read_pty())

    try:
        await websocket.send(json.dumps({
            "type": "output",
            "data": f"JARVIS PTY connected. cwd={cwd}\r\n$ ",
        }))

        async for raw in websocket:
            try:
                msg = json.loads(raw)
            except Exception:
                continue

            msg_type = msg.get("type")

            if msg_type == "input":
                data = msg.get("data", "")
                if data:
                    os.write(master_fd, data.encode("utf-8", errors="replace"))

            elif msg_type == "resize":
                # optional later
                pass

            elif msg_type == "cwd":
                new_cwd = msg.get("cwd", "").strip()
                if new_cwd:
                    os.write(master_fd, f"cd {new_cwd}\n".encode("utf-8"))

    finally:
        reader_task.cancel()

        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
        except Exception:
            pass

        try:
            os.close(master_fd)
        except Exception:
            pass


async def main():
    print(f"[PTY] WebSocket PTY server on ws://{HOST}:{PORT}")
    async with websockets.serve(terminal_session, HOST, PORT):
        await asyncio.Future()


if __name__ == "__main__":
    asyncio.run(main())