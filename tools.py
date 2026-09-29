"""Schema-driven tool registry and idempotency protection."""
from __future__ import annotations
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple


@dataclass
class ToolDefinition:
    name: str
    description: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    is_state_modifying: bool = False
    required_params: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolDefinition:
        params = data.get("parameters", {})
        # Parameters might be JSON Schema format
        required = []
        if isinstance(params, dict):
            required = params.get("required", [])

        # Check explicit or heuristic state modification indicators
        is_modifying = data.get("is_state_modifying")
        if is_modifying is None:
            # check alternative flags or naming conventions
            is_modifying = data.get("mutating", False)
            if not is_modifying:
                modifying_verbs = ["book", "cancel", "create", "delete", "update", "modify", "charge", "pay", "order"]
                name_lower = data.get("name", "").lower()
                is_modifying = any(verb in name_lower for verb in modifying_verbs)

        return cls(
            name=data.get("name", ""),
            description=data.get("description", ""),
            parameters=params,
            is_state_modifying=bool(is_modifying),
            required_params=required,
        )


class ToolRegistry:
    """Dynamic tool repository loaded from scenario tool manifests."""

    def __init__(self):
        self.tools: Dict[str, ToolDefinition] = {}

    def register_manifest(self, manifest_payload: Dict[str, Any]) -> None:
        """Parse dynamic tool definitions from scenario manifest event."""
        tools_list = manifest_payload.get("tools", [])
        for tool_dict in tools_list:
            tool_def = ToolDefinition.from_dict(tool_dict)
            self.tools[tool_def.name] = tool_def

    def register_tool(self, tool_def: ToolDefinition) -> None:
        self.tools[tool_def.name] = tool_def

    def get_tool(self, name: str) -> Optional[ToolDefinition]:
        return self.tools.get(name)

    def is_state_modifying(self, name: str) -> bool:
        tool = self.tools.get(name)
        return tool.is_state_modifying if tool else False

    def validate_call(self, name: str, arguments: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate tool existence and parameter constraints against schema."""
        if name not in self.tools:
            return False, f"Unknown tool: '{name}'"

        tool = self.tools[name]
        for req in tool.required_params:
            if req not in arguments or arguments[req] is None or arguments[req] == "":
                return False, f"Missing required parameter '{req}' for tool '{name}'"

        return True, None


class IdempotencyGuard:
    """Enforces zero-duplicate state-changing calls across the session."""

    def __init__(self):
        # Maps idempotency_key -> (call_id, status: 'dispatched' | 'completed' | 'cancelled')
        self._action_records: Dict[str, Tuple[str, str]] = {}
        self._executed_keys: Set[str] = set()

    def generate_key(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Create deterministic key from tool name and canonical JSON of arguments."""
        canonical_args = json.dumps(arguments, sort_keys=True, default=str)
        raw = f"{tool_name}:{canonical_args}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def can_dispatch(self, tool_name: str, arguments: Dict[str, Any], is_state_modifying: bool) -> Tuple[bool, Optional[str]]:
        """Check if call is safe to dispatch.

        Read-only calls can always be dispatched or retried.
        State-modifying calls are strictly blocked if already dispatched or completed.
        """
        if not is_state_modifying:
            return True, None

        key = self.generate_key(tool_name, arguments)
        if key in self._executed_keys:
            return False, f"Idempotency violation: State-changing call '{tool_name}' already executed."

        if key in self._action_records:
            prev_call_id, status = self._action_records[key]
            if status in ("dispatched", "completed"):
                return False, f"Duplicate state-changing call '{tool_name}' prevented (call_id={prev_call_id}, status={status})."

        return True, None

    def record_dispatch(self, call_id: str, tool_name: str, arguments: Dict[str, Any], is_state_modifying: bool) -> None:
        if is_state_modifying:
            key = self.generate_key(tool_name, arguments)
            self._action_records[key] = (call_id, "dispatched")

    def record_completion(self, tool_name: str, arguments: Dict[str, Any], is_state_modifying: bool) -> None:
        if is_state_modifying:
            key = self.generate_key(tool_name, arguments)
            call_id = self._action_records.get(key, ("unknown", ""))[0]
            self._action_records[key] = (call_id, "completed")
            self._executed_keys.add(key)

    def record_cancellation(self, tool_name: str, arguments: Dict[str, Any], is_state_modifying: bool) -> None:
        if is_state_modifying:
            key = self.generate_key(tool_name, arguments)
            if key in self._action_records:
                call_id = self._action_records[key][0]
                self._action_records[key] = (call_id, "cancelled")

    def reset(self) -> None:
        self._action_records.clear()
        self._executed_keys.clear()
