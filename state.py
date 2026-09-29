"""Session-scoped State and Slot Management with localized repair support."""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Set
from schemas.actions import StateSnapshot


class SessionStateManager:
    """Maintains session-scoped slot state and provides conversational self-repair."""

    def __init__(self, session_id: str = "default_session"):
        self.session_id = session_id
        self.intent: Optional[str] = None
        self.slots: Dict[str, Any] = {}
        self.slot_history: Dict[str, List[Any]] = {}
        self.active_calls: Dict[str, Dict[str, Any]] = {}  # call_id -> metadata (tool_name, args, epoch)
        self.cancelled_calls: Set[str] = set()
        self.completed_calls: Dict[str, Any] = {}  # call_id -> result
        self.turn_id: int = 1
        self.epoch: int = 0
        self.status: str = "idle"

    def reset(self) -> None:
        """Reset all state for a new session (enforces no cross-session caching)."""
        self.intent = None
        self.slots.clear()
        self.slot_history.clear()
        self.active_calls.clear()
        self.cancelled_calls.clear()
        self.completed_calls.clear()
        self.turn_id = 1
        self.epoch = 0
        self.status = "idle"

    def increment_epoch(self) -> int:
        """Increment epoch upon interruption or corrective turn."""
        self.epoch += 1
        return self.epoch

    def next_turn(self) -> int:
        """Advance to next conversational turn."""
        self.turn_id += 1
        return self.turn_id

    def set_intent(self, intent: str) -> None:
        self.intent = intent

    def set_slot(self, key: str, value: Any) -> None:
        """Update or insert a slot with historical tracking for repair audit."""
        if key not in self.slot_history:
            self.slot_history[key] = []
        if key in self.slots and self.slots[key] != value:
            self.slot_history[key].append(self.slots[key])
        self.slots[key] = value

    def repair_slot(self, key: str, new_value: Any) -> None:
        """Apply a localized slot correction while preserving other session slots."""
        self.set_slot(key, new_value)

    def update_slots(self, new_slots: Dict[str, Any]) -> None:
        """Merge a dictionary of slots into the current session state."""
        for k, v in new_slots.items():
            self.set_slot(k, v)

    def register_active_call(self, call_id: str, tool_name: str, arguments: Dict[str, Any], epoch: int) -> None:
        """Register a dispatched asynchronous tool call."""
        self.active_calls[call_id] = {
            "tool_name": tool_name,
            "arguments": arguments,
            "epoch": epoch,
        }
        self.status = "in_progress"

    def unregister_call(self, call_id: str) -> Optional[Dict[str, Any]]:
        """Remove a call once completed."""
        meta = self.active_calls.pop(call_id, None)
        if not self.active_calls and self.status == "in_progress":
            self.status = "idle"
        return meta

    def mark_cancelled(self, call_id: str) -> None:
        """Record that a call has been cancelled."""
        self.active_calls.pop(call_id, None)
        self.cancelled_calls.add(call_id)
        if not self.active_calls and self.status == "in_progress":
            self.status = "idle"

    def is_cancelled(self, call_id: str) -> bool:
        return call_id in self.cancelled_calls

    def record_result(self, call_id: str, result: Any) -> None:
        self.completed_calls[call_id] = result

    def get_snapshot(self) -> StateSnapshot:
        """Emit an immutable snapshot of current session state."""
        return StateSnapshot(
            intent=self.intent,
            slots=dict(self.slots),
            active_calls=list(self.active_calls.keys()),
            status=self.status,
            turn_id=self.turn_id,
            epoch=self.epoch,
        )
