"""Coordination layer managing turn epochs, prompt tool cancellations, and grace period filtering."""
from __future__ import annotations
from typing import Any, Dict, List, Optional, Tuple
from actions import OutputAction, StateSnapshot
from events import InputEvent
from state import SessionStateManager
from tools import IdempotencyGuard, ToolRegistry


class CoordinationLayer:
    """Coordinates non-blocking execution, millisecond cancellation, and state consistency."""

    def __init__(
        self,
        state_manager: SessionStateManager,
        tool_registry: ToolRegistry,
        idempotency_guard: IdempotencyGuard,
    ):
        self.state_manager = state_manager
        self.tool_registry = tool_registry
        self.idempotency_guard = idempotency_guard
        self._call_counter = 0

    def next_call_id(self, tool_name: str) -> str:
        """Generate unique call_id adhering to protocol standards."""
        self._call_counter += 1
        return f"call_{tool_name}_{self._call_counter:03d}"

    def handle_interruption(
        self,
        timestamp: float,
        reason: str = "User interruption signal received",
    ) -> List[OutputAction]:
        """Trigger prompt cancellation of all in-flight tool calls within millisecond grace period.

        Returns list of OutputAction(action_type=TOOL_CANCEL) for immediate emission.
        """
        # 1. Advance epoch
        new_epoch = self.state_manager.increment_epoch()

        # 2. Collect in-flight calls
        active_calls = list(self.state_manager.active_calls.items())
        cancellation_actions: List[OutputAction] = []

        # 3. Promptly cancel all active calls
        for call_id, meta in active_calls:
            tool_name = meta.get("tool_name", "unknown")
            args = meta.get("arguments", {})
            is_modifying = self.tool_registry.is_state_modifying(tool_name)

            # Mark state & idempotency
            self.state_manager.mark_cancelled(call_id)
            self.idempotency_guard.record_cancellation(tool_name, args, is_modifying)

            # Emit cancellation action with fresh state snapshot
            cancel_action = OutputAction.tool_cancel(
                timestamp=timestamp,
                call_id=call_id,
                reason=reason,
                snapshot=self.state_manager.get_snapshot(),
                epoch=new_epoch,
            )
            cancellation_actions.append(cancel_action)

        # Update status
        self.state_manager.status = "listening"

        return cancellation_actions

    def should_process_tool_result(self, call_id: str, event_timestamp: float) -> Tuple[bool, Optional[str]]:
        """Determine if an incoming TOOL_RESULT is valid or should be dropped due to cancellation/stale epoch.

        Prevents stale re-runs and state corruption.
        """
        # If call was explicitly cancelled
        if self.state_manager.is_cancelled(call_id):
            return False, f"Call '{call_id}' was cancelled due to interruption."

        # If call is not in active calls, it might have already finished or been purged
        if call_id not in self.state_manager.active_calls and call_id not in self.state_manager.completed_calls:
            return False, f"Call '{call_id}' is unknown or already expired."

        return True, None

    def register_call(
        self,
        timestamp: float,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> Tuple[Optional[OutputAction], Optional[str]]:
        """Validate and construct a non-blocking TOOL_CALL action."""
        # 1. Validate schema
        is_valid, err = self.tool_registry.validate_call(tool_name, arguments)
        if not is_valid:
            return None, err

        is_modifying = self.tool_registry.is_state_modifying(tool_name)

        # 2. Check idempotency for state-modifying actions
        can_run, idemp_err = self.idempotency_guard.can_dispatch(tool_name, arguments, is_modifying)
        if not can_run:
            return None, idemp_err

        # 3. Create call ID
        call_id = self.next_call_id(tool_name)
        current_epoch = self.state_manager.epoch

        # 4. Register in state and idempotency guard
        self.state_manager.register_active_call(call_id, tool_name, arguments, current_epoch)
        self.idempotency_guard.record_dispatch(call_id, tool_name, arguments, is_modifying)

        # 5. Build action
        action = OutputAction.tool_call(
            timestamp=timestamp,
            call_id=call_id,
            tool_name=tool_name,
            arguments=arguments,
            snapshot=self.state_manager.get_snapshot(),
            epoch=current_epoch,
            is_state_modifying=is_modifying,
        )
        return action, None

    def complete_call(self, call_id: str, tool_name: str, result: Any) -> None:
        """Mark a tool call as completed cleanly."""
        meta = self.state_manager.unregister_call(call_id)
        args = meta.get("arguments", {}) if meta else {}
        is_modifying = self.tool_registry.is_state_modifying(tool_name)
        self.idempotency_guard.record_completion(tool_name, args, is_modifying)
        self.state_manager.record_result(call_id, result)
