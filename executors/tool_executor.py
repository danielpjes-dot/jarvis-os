from __future__ import annotations

import json
import time
import traceback
from typing import Any, Callable, Dict, Optional


class ToolExecutor:
    def __init__(
        self,
        tool_map: dict,
        emit_event: Callable[[str, str, Optional[Dict[str, Any]]], None],
        truncate_text: Callable[[Any, int], str],
    ):
        self.tool_map = tool_map
        self.emit_event = emit_event
        self.truncate_text = truncate_text

    def execute(self, tool_name: str, args: Optional[dict] = None) -> str:
        args = args or {}
        executor = self.tool_map.get(tool_name)

        if not executor:
            return json.dumps({"ok": False, "error": f"Unknown tool: {tool_name}"}, ensure_ascii=False)

        started = time.time()
        self.emit_event("tool_start", f"Running tool {tool_name}", {"tool": tool_name, "args": args})

        try:
            result = executor(**args)
            elapsed = time.time() - started

            self.emit_event(
                "tool_result",
                f"Tool {tool_name} completed",
                {
                    "tool": tool_name,
                    "elapsed_sec": round(elapsed, 3),
                    "result_preview": self.truncate_text(result, 500),
                },
            )

            if isinstance(result, str):
                return self.truncate_text(result, 12000)

            return json.dumps(result, ensure_ascii=False, default=str)

        except Exception as e:
            self.emit_event(
                "tool_error",
                f"Tool {tool_name} failed",
                {
                    "tool": tool_name,
                    "error": str(e),
                    "traceback": traceback.format_exc(limit=3),
                },
            )

            return json.dumps(
                {
                    "ok": False,
                    "tool": tool_name,
                    "error": str(e),
                },
                ensure_ascii=False,
            )