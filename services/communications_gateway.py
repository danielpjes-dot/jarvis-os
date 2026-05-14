from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional


class CommunicationsGateway:
    """
    Safe communications gateway.

    v1 behavior:
    - does not send external messages directly
    - writes communication requests to an approval queue
    - HUD/API can later approve, edit, reject, or send
    """

    def __init__(self, vault_dir: Path):
        self.vault_dir = Path(vault_dir)
        self.queue_path = self.vault_dir / ".jarvis" / "communications" / "approval_queue.json"

    def _now_iso(self) -> str:
        return datetime.utcnow().isoformat(timespec="seconds") + "Z"

    def _load_queue(self) -> Dict[str, Any]:
        if not self.queue_path.exists():
            return {"items": []}

        try:
            data = json.loads(self.queue_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                data.setdefault("items", [])
                return data
        except Exception:
            pass

        return {"items": []}

    def _save_queue(self, queue: Dict[str, Any]) -> None:
        self.queue_path.parent.mkdir(parents=True, exist_ok=True)
        self.queue_path.write_text(
            json.dumps(queue, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def list_requests(self, status: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        queue = self._load_queue()
        items = queue.get("items", [])

        if status:
            items = [item for item in items if item.get("status") == status]

        return items[-limit:]

    def create_request(
        self,
        channel: str,
        target: str,
        subject: str,
        body: str,
        priority: str = "normal",
        requires_approval: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        request_id = "comm_" + str(uuid.uuid4())[:8]
        now = self._now_iso()

        item = {
            "id": request_id,
            "channel": channel,
            "target": target,
            "subject": subject,
            "body": body,
            "priority": priority,
            "requires_approval": requires_approval,
            "status": "pending_approval" if requires_approval else "queued",
            "created_at": now,
            "updated_at": now,
            "metadata": metadata or {},
            "history": [
                {
                    "time": now,
                    "event": "created",
                    "status": "pending_approval" if requires_approval else "queued",
                }
            ],
        }

        queue = self._load_queue()
        queue.setdefault("items", []).append(item)
        self._save_queue(queue)

        return {
            "ok": True,
            "request": item,
        }

    def update_request(
        self,
        request_id: str,
        updates: Dict[str, Any],
    ) -> Dict[str, Any]:
        queue = self._load_queue()
        now = self._now_iso()

        for item in queue.get("items", []):
            if item.get("id") == request_id:
                allowed = {"channel", "target", "subject", "body", "priority", "metadata"}
                for key, value in updates.items():
                    if key in allowed:
                        item[key] = value

                item["updated_at"] = now
                item.setdefault("history", []).append(
                    {
                        "time": now,
                        "event": "updated",
                        "updates": {k: v for k, v in updates.items() if k in allowed},
                    }
                )

                self._save_queue(queue)
                return {"ok": True, "request": item}

        return {"ok": False, "error": f"Communication request not found: {request_id}"}

    def set_status(
        self,
        request_id: str,
        status: str,
        note: str = "",
    ) -> Dict[str, Any]:
        queue = self._load_queue()
        now = self._now_iso()

        valid_statuses = {
            "pending_approval",
            "approved",
            "rejected",
            "queued",
            "sent",
            "failed",
            "cancelled",
        }

        if status not in valid_statuses:
            return {"ok": False, "error": f"Invalid status: {status}"}

        for item in queue.get("items", []):
            if item.get("id") == request_id:
                item["status"] = status
                item["updated_at"] = now
                item.setdefault("history", []).append(
                    {
                        "time": now,
                        "event": "status_changed",
                        "status": status,
                        "note": note,
                    }
                )

                self._save_queue(queue)
                return {"ok": True, "request": item}

        return {"ok": False, "error": f"Communication request not found: {request_id}"}

    def approve_request(self, request_id: str, note: str = "") -> Dict[str, Any]:
        return self.set_status(request_id, "approved", note=note)

    def reject_request(self, request_id: str, note: str = "") -> Dict[str, Any]:
        return self.set_status(request_id, "rejected", note=note)

    def cancel_request(self, request_id: str, note: str = "") -> Dict[str, Any]:
        return self.set_status(request_id, "cancelled", note=note)