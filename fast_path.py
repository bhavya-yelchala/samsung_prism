"""Fast-path reflex engine and conversational floor manager."""
from __future__ import annotations
from typing import Any, Dict, List, Optional
from actions import OutputAction, StateSnapshot
from state import SessionStateManager


class FastPathReflexEngine:
    """Delivers sub-200ms conversational responses, floor management, and latency hiding."""

    def __init__(self, state_manager: SessionStateManager):
        self.state_manager = state_manager
        self._last_filler_time: float = -10000.0
        self._filler_cadence_ms: float = 800.0  # Minimum interval to avoid excessive fillers

    def reset(self) -> None:
        self._last_filler_time = -10000.0

    def generate_acknowledgment(
        self,
        timestamp: float,
        intent: Optional[str],
        slots: Dict[str, Any],
        tool_name: Optional[str] = None,
    ) -> Optional[OutputAction]:
        """Generate a contextual filler within a few hundred ms to hold the floor without false claims."""
        # Cadence check to avoid excessive fillers
        if (timestamp - self._last_filler_time) < self._filler_cadence_ms:
            return None

        text = self._select_filler_text(intent, slots, tool_name)
        if not text:
            return None

        self._last_filler_time = timestamp

        return OutputAction.spoken_filler(
            timestamp=timestamp,
            text=text,
            snapshot=self.state_manager.get_snapshot(),
            epoch=self.state_manager.epoch,
        )

    def generate_clarification(
        self,
        timestamp: float,
        question: str,
        missing_slots: List[str],
    ) -> OutputAction:
        """Immediately issue a clarification request for ambiguous perceptions or missing slots."""
        self.state_manager.status = "clarifying"
        return OutputAction.clarification(
            timestamp=timestamp,
            question=question,
            missing_slots=missing_slots,
            snapshot=self.state_manager.get_snapshot(),
            epoch=self.state_manager.epoch,
        )

    def _select_filler_text(
        self,
        intent: Optional[str],
        slots: Dict[str, Any],
        tool_name: Optional[str],
    ) -> Optional[str]:
        """Produce meaningful, truthful progress narration without false completion claims."""
        if tool_name == "flight_search" or intent in ("search_flight", "flight_search"):
            dest = slots.get("destination")
            if dest:
                return f"Looking up flights to {dest}..."
            return "Searching for available flights..."

        elif tool_name == "book_flight" or intent in ("book_flight", "booking_flight"):
            flight_id = slots.get("flight_id") or slots.get("destination")
            return f"Processing your booking request now..."

        elif tool_name == "create_ticket" or intent == "create_ticket":
            return "Generating your support ticket..."

        elif tool_name in ("lookup_manual", "device_troubleshoot") or intent == "troubleshoot_device":
            device = slots.get("device") or slots.get("detected_device", "device")
            return f"Checking the {device} technical manual..."

        elif intent == "general_query":
            return "Checking that for you..."

        # Fallback default acknowledgment if turn is significant
        if intent:
            return f"Checking on your request..."
        return None
