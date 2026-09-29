"""Mock execution environment with deterministic latency and fault injection."""
from __future__ import annotations
import copy
from typing import Any, Dict, List, Optional, Tuple


class MockEnvironment:
    """Simulates external tools with configurable latency, fault injection, and cancellation tracking."""

    def __init__(self):
        # Latency in virtual milliseconds
        self.latencies: Dict[str, float] = {
            "flight_search": 600.0,
            "book_flight": 900.0,
            "create_ticket": 700.0,
            "lookup_manual": 500.0,
        }
        # Injected faults: tool_name -> failure message
        self.faults: Dict[str, str] = {}
        # Fault trigger counts: tool_name -> number of times to fail before succeeding
        self.fault_counts: Dict[str, int] = {}
        # Tracking mutations to detect illegal double modifications
        self.executed_mutations: List[Dict[str, Any]] = []
        self.cancelled_calls: List[str] = []

    def set_fault(self, tool_name: str, error_message: str, count: int = 1) -> None:
        self.faults[tool_name] = error_message
        self.fault_counts[tool_name] = count

    def get_latency(self, tool_name: str) -> float:
        return self.latencies.get(tool_name, 500.0)

    def cancel_call(self, call_id: str) -> None:
        self.cancelled_calls.append(call_id)

    def execute_tool(self, tool_name: str, arguments: Dict[str, Any], call_id: str) -> Tuple[Optional[Any], Optional[str]]:
        """Simulate tool execution with deterministic outputs and fault checking."""
        # Check fault injection
        if tool_name in self.fault_counts and self.fault_counts[tool_name] > 0:
            self.fault_counts[tool_name] -= 1
            err = self.faults.get(tool_name, "Simulated transient API error")
            return None, err

        # Check state-modifying tracking
        if tool_name in ("book_flight", "create_ticket"):
            self.executed_mutations.append({
                "call_id": call_id,
                "tool_name": tool_name,
                "arguments": copy.deepcopy(arguments),
            })

        # Return mock results
        if tool_name == "flight_search":
            dest = arguments.get("destination", "Chicago")
            date = arguments.get("date", "2026-10-15")
            return {
                "destination": dest,
                "date": date,
                "flights": [
                    {"flight_id": f"FL-{dest[:3].upper()}01", "time": "08:30 AM", "price": 280},
                    {"flight_id": f"FL-{dest[:3].upper()}02", "time": "02:15 PM", "price": 310},
                ],
            }, None

        elif tool_name == "book_flight":
            dest = arguments.get("destination", "Unknown")
            flight_id = arguments.get("flight_id", "FL-101")
            return {
                "booking_reference": f"CONF-{flight_id[-3:]}-998",
                "status": "confirmed",
                "destination": dest,
                "passenger_count": arguments.get("passengers", 1),
            }, None

        elif tool_name == "create_ticket":
            return {
                "ticket_id": f"TCK-{len(self.executed_mutations):03d}",
                "status": "open",
                "priority": "high",
            }, None

        elif tool_name == "lookup_manual":
            device = arguments.get("device", "Samsung Device")
            error_code = arguments.get("error_code")
            symptom = arguments.get("symptom")

            if error_code == "E-404":
                sol = "Inspect network gateway configuration and re-pair wireless connection."
            elif symptom == "blinking_indicator":
                sol = "Power cycle the device: unplug for 60 seconds, then reconnect."
            else:
                sol = "Refer to section 4.2 of the user manual for diagnostic reset steps."

            return {
                "device": device,
                "error_code": error_code,
                "solution": sol,
            }, None

        # Generic / unseen tool
        return {
            "status": "success",
            "executed_arguments": arguments,
        }, None
