from __future__ import annotations

from typing import Any, Callable, Dict, Optional


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, dict] = {}
        self._executors: Dict[str, Callable[..., Any]] = {}

    def register(self, definition: dict, executor: Callable[..., Any]) -> None:
        name = definition["function"]["name"]
        self._tools[name] = definition
        self._executors[name] = executor

    def definitions(self) -> list[dict]:
        return list(self._tools.values())

    def by_name(self) -> dict:
        return dict(self._tools)

    def names(self) -> list[str]:
        return sorted(self._tools.keys())

    def execute(self, name: str, args: Optional[dict] = None) -> Any:
        if name not in self._executors:
            return {"ok": False, "error": f"Tool executor not found: {name}"}

        return self._executors[name](**(args or {}))