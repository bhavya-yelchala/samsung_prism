"""Output Action and State Snapshot schemas for the real-time interruptible agent."""
from __future__ import annotations
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ActionType(str, Enum):
    SPOKEN_FILLER = "SPOKEN_FILLER"
    TOOL_CALL = "TOOL_CALL"
    TOOL_CANCEL = "TOOL_CANCEL"
    CLARIFICATION_REQUEST = "CLARIFICATION_REQUEST"
    FINAL_RESPONSE = "FINAL_RESPONSE"


@dataclass
class StateSnapshot:
    intent: Optional[str] = None
    slots: Dict[str, Any] = field(default_factory=dict)
    active_calls: List[str] = field(default_factory=list)
    status: str = "idle"  # idle, in_progress, clarifying, completed, cancelled
    turn_id: int = 1
    epoch: int = 0

    def copy(self) -> StateSnapshot:
        return StateSnapshot(
            intent=self.intent,
            slots=dict(self.slots),
            active_calls=list(self.active_calls),
            status=self.status,
            turn_id=self.turn_id,
            epoch=self.epoch,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "intent": self.intent,
            "slots": self.slots,
            "active_calls": self.active_calls,
            "status": self.status,
            "turn_id": self.turn_id,
            "epoch": self.epoch,
        }


@dataclass
class OutputAction:
    timestamp: float  # Virtual clock in milliseconds
    action_type: ActionType
    payload: Dict[str, Any] = field(default_factory=dict)
    call_id: Optional[str] = None
    state_snapshot: StateSnapshot = field(default_factory=StateSnapshot)
    epoch: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "action_type": self.action_type.value if isinstance(self.action_type, Enum) else self.action_type,
            "call_id": self.call_id,
            "payload": self.payload,
            "state_snapshot": self.state_snapshot.to_dict(),
            "epoch": self.epoch,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> OutputAction:
        action_type = ActionType(data["action_type"]) if isinstance(data["action_type"], str) else data["action_type"]
        snap_data = data.get("state_snapshot", {})
        snapshot = StateSnapshot(
            intent=snap_data.get("intent"),
            slots=snap_data.get("slots", {}),
            active_calls=snap_data.get("active_calls", []),
            status=snap_data.get("status", "idle"),
            turn_id=snap_data.get("turn_id", 1),
            epoch=snap_data.get("epoch", 0),
        )
        return cls(
            timestamp=float(data["timestamp"]),
            action_type=action_type,
            payload=data.get("payload", {}),
            call_id=data.get("call_id"),
            state_snapshot=snapshot,
            epoch=data.get("epoch", 0),
        )

    # Convenience constructors
    @classmethod
    def spoken_filler(
        cls,
        timestamp: float,
        text: str,
        snapshot: StateSnapshot,
        epoch: int,
    ) -> OutputAction:
        return cls(
            timestamp=timestamp,
            action_type=ActionType.SPOKEN_FILLER,
            payload={"text": text},
            state_snapshot=snapshot.copy(),
            epoch=epoch,
        )

    @classmethod
    def tool_call(
        cls,
        timestamp: float,
        call_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
        snapshot: StateSnapshot,
        epoch: int,
        is_state_modifying: bool = False,
    ) -> OutputAction:
        snap = snapshot.copy()
        if call_id not in snap.active_calls:
            snap.active_calls.append(call_id)
        snap.status = "in_progress"
        return cls(
            timestamp=timestamp,
            action_type=ActionType.TOOL_CALL,
            call_id=call_id,
            payload={
                "tool_name": tool_name,
                "arguments": arguments,
                "is_state_modifying": is_state_modifying,
            },
            state_snapshot=snap,
            epoch=epoch,
        )

    @classmethod
    def tool_cancel(
        cls,
        timestamp: float,
        call_id: str,
        reason: str,
        snapshot: StateSnapshot,
        epoch: int,
    ) -> OutputAction:
        snap = snapshot.copy()
        if call_id in snap.active_calls:
            snap.active_calls.remove(call_id)
        return cls(
            timestamp=timestamp,
            action_type=ActionType.TOOL_CANCEL,
            call_id=call_id,
            payload={"reason": reason},
            state_snapshot=snap,
            epoch=epoch,
        )

    @classmethod
    def clarification(
        cls,
        timestamp: float,
        question: str,
        missing_slots: List[str],
        snapshot: StateSnapshot,
        epoch: int,
    ) -> OutputAction:
        snap = snapshot.copy()
        snap.status = "clarifying"
        return cls(
            timestamp=timestamp,
            action_type=ActionType.CLARIFICATION_REQUEST,
            payload={"question": question, "missing_slots": missing_slots},
            state_snapshot=snap,
            epoch=epoch,
        )

    @classmethod
    def final_response(
        cls,
        timestamp: float,
        text: str,
        snapshot: StateSnapshot,
        epoch: int,
        metadata: Optional[Dict[str, Any]] = None,
        status: str = "completed",
    ) -> OutputAction:
        snap = snapshot.copy()
        snap.status = status
        return cls(
            timestamp=timestamp,
            action_type=ActionType.FINAL_RESPONSE,
            payload={"text": text, "metadata": metadata or {}},
            state_snapshot=snap,
            epoch=epoch,
        )
