"""Virtual Clock Streaming Harness for deterministic event replay and complete trace logging."""
from __future__ import annotations
import heapq
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
from schemas.events import EventType, InputEvent
from schemas.actions import ActionType, OutputAction
from agent.core import InterruptibleRealTimeAgent
from harness.mock_env import MockEnvironment


@dataclass(order=True)
class ScheduledEvent:
    timestamp: float
    event: InputEvent = field(compare=False)
    order_id: int = 0


@dataclass
class ScenarioTrace:
    scenario_id: str
    events_in: List[Dict[str, Any]] = field(default_factory=list)
    actions_out: List[Dict[str, Any]] = field(default_factory=list)
    total_virtual_duration_ms: float = 0.0
    first_spoken_action_latency_ms: Optional[float] = None
    first_spoken_action_timestamp: Optional[float] = None
    interrupted_latencies_ms: List[float] = field(default_factory=list)
    cancellations_emitted: List[str] = field(default_factory=list)
    tool_calls_dispatched: List[str] = field(default_factory=list)
    mutations_count: int = 0


class VirtualClockHarness:
    """Replays deterministic event streams against the agent and tracks millisecond traces."""

    def __init__(self, mock_env: Optional[MockEnvironment] = None):
        self.mock_env = mock_env or MockEnvironment()
        self.current_time_ms: float = 0.0
        self._event_queue: List[ScheduledEvent] = []
        self._event_order_seq = 0
        self._active_scheduled_calls: Dict[str, ScheduledEvent] = {}  # call_id -> ScheduledEvent

    def schedule_event(self, event: InputEvent) -> None:
        """Add an event to the virtual timeline."""
        self._event_order_seq += 1
        scheduled = ScheduledEvent(
            timestamp=event.timestamp,
            event=event,
            order_id=self._event_order_seq,
        )
        heapq.heappush(self._event_queue, scheduled)

    def schedule_tool_result(self, timestamp: float, call_id: str, tool_name: str, args: Dict[str, Any]) -> None:
        """Schedule future completion of a mock tool."""
        res, err = self.mock_env.execute_tool(tool_name, args, call_id)
        latency = self.mock_env.get_latency(tool_name)
        finish_time = timestamp + latency

        result_event = InputEvent.tool_result(
            timestamp=finish_time,
            call_id=call_id,
            tool_name=tool_name,
            result=res,
            error=err,
            execution_time_ms=latency,
        )
        self._event_order_seq += 1
        scheduled = ScheduledEvent(
            timestamp=finish_time,
            event=result_event,
            order_id=self._event_order_seq,
        )
        self._active_scheduled_calls[call_id] = scheduled
        heapq.heappush(self._event_queue, scheduled)

    def run_scenario(
        self,
        scenario_id: str,
        events: List[InputEvent],
        agent: InterruptibleRealTimeAgent,
    ) -> ScenarioTrace:
        """Execute a full scenario deterministically across the virtual timeline."""
        # 1. Reset state
        self.current_time_ms = 0.0
        self._event_queue.clear()
        self._event_order_seq = 0
        self._active_scheduled_calls.clear()
        agent.reset()

        trace = ScenarioTrace(scenario_id=scenario_id)

        # 2. Queue all initial scenario events
        for ev in events:
            self.schedule_event(ev)

        first_input_timestamp = events[0].timestamp if events else 0.0
        last_interruption_time: Optional[float] = None

        # 3. Step through virtual timeline
        while self._event_queue:
            scheduled_item = heapq.heappop(self._event_queue)
            self.current_time_ms = scheduled_item.timestamp
            current_event = scheduled_item.event

            # Track interruption timing for latency measurement
            if current_event.type == EventType.INTERRUPTION_SIGNAL:
                last_interruption_time = current_event.timestamp

            # Record event in trace
            trace.events_in.append({
                "timestamp": self.current_time_ms,
                "event": current_event.to_dict(),
            })

            # Process event in agent
            actions = agent.process_event_step(current_event)

            for act in actions:
                trace.actions_out.append({
                    "timestamp": act.timestamp,
                    "action": act.to_dict(),
                })

                # Latency tracking: first substantive spoken action
                if act.action_type in (ActionType.SPOKEN_FILLER, ActionType.CLARIFICATION_REQUEST, ActionType.FINAL_RESPONSE):
                    if trace.first_spoken_action_latency_ms is None:
                        trace.first_spoken_action_timestamp = act.timestamp
                        trace.first_spoken_action_latency_ms = act.timestamp - first_input_timestamp

                    if last_interruption_time is not None:
                        latency_since_interrupt = act.timestamp - last_interruption_time
                        trace.interrupted_latencies_ms.append(latency_since_interrupt)
                        last_interruption_time = None

                # Handle TOOL_CALL
                if act.action_type == ActionType.TOOL_CALL:
                    call_id = act.call_id
                    trace.tool_calls_dispatched.append(call_id)
                    tool_name = act.payload.get("tool_name", "")
                    arguments = act.payload.get("arguments", {})
                    self.schedule_tool_result(self.current_time_ms, call_id, tool_name, arguments)

                # Handle TOOL_CANCEL
                elif act.action_type == ActionType.TOOL_CANCEL:
                    cancel_call_id = act.call_id
                    trace.cancellations_emitted.append(cancel_call_id)
                    self.mock_env.cancel_call(cancel_call_id)

        trace.total_virtual_duration_ms = self.current_time_ms
        trace.mutations_count = len(self.mock_env.executed_mutations)
        return trace
