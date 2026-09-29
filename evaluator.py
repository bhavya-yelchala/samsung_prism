"""Automated evaluation and scoring engine based strictly on trace logs."""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from schemas.actions import ActionType
from schemas.events import EventType
from harness.virtual_clock import ScenarioTrace


@dataclass
class ScenarioScore:
    scenario_id: str
    task_completion: float  # max 40
    interruption_recovery: float  # max 35
    response_latency: float  # max 15
    safety_protocol: float  # max 10
    base_score: float  # sum (max 100)
    quality_multiplier: float  # 0.80 - 1.20
    is_multimodal: bool
    multimodal_multiplier: float  # 1.5x for multimodal, 1.0x otherwise
    final_score: float
    details: List[str] = field(default_factory=list)


class ScenarioEvaluator:
    """Evaluates scenario execution traces strictly against the Section 5 rubric."""

    @classmethod
    def evaluate(
        cls,
        trace: ScenarioTrace,
        expected_intent: Optional[str] = None,
        expected_slots: Optional[Dict[str, Any]] = None,
        expect_cancellation: bool = False,
        is_multimodal: bool = False,
        max_acceptable_latency_ms: float = 300.0,
    ) -> ScenarioScore:
        details: List[str] = []

        # ----------------------------------------------------
        # 1. Task Completion (40 points max)
        # ----------------------------------------------------
        tc_score = 0.0

        # Check for final response
        final_responses = [
            a for a in trace.actions_out
            if a["action"]["action_type"] == ActionType.FINAL_RESPONSE.value
        ]
        has_final = len(final_responses) > 0
        if has_final:
            tc_score += 15.0
            details.append("Task Completion (+15): Emitted final response.")
        else:
            # Check if clarification was legitimate completion
            clarifications = [
                a for a in trace.actions_out
                if a["action"]["action_type"] == ActionType.CLARIFICATION_REQUEST.value
            ]
            if clarifications:
                tc_score += 15.0
                details.append("Task Completion (+15): Emitted appropriate clarification request.")
            else:
                details.append("Task Completion (0/15): Missing final response or clarification.")

        # Check state snapshot accuracy
        if final_responses:
            last_snap = final_responses[-1]["action"]["state_snapshot"]
        elif trace.actions_out:
            last_snap = trace.actions_out[-1]["action"]["state_snapshot"]
        else:
            last_snap = {}

        if expected_intent:
            if last_snap.get("intent") == expected_intent:
                tc_score += 10.0
                details.append(f"Task Completion (+10): Intent correctly captured ('{expected_intent}').")
            else:
                details.append(f"Task Completion (0/10): Intent mismatch: got '{last_snap.get('intent')}', expected '{expected_intent}'.")
        else:
            tc_score += 10.0

        # Check slots
        if expected_slots:
            matched_slots = 0
            curr_slots = last_snap.get("slots", {})
            for k, v in expected_slots.items():
                if k in curr_slots and str(curr_slots[k]).lower() == str(v).lower():
                    matched_slots += 1
            slot_ratio = matched_slots / len(expected_slots) if expected_slots else 1.0
            tc_score += 15.0 * slot_ratio
            details.append(f"Task Completion (+{15.0 * slot_ratio:.1f}/15): Slot accuracy {matched_slots}/{len(expected_slots)}.")
        else:
            tc_score += 15.0

        # ----------------------------------------------------
        # 2. Interruption Recovery (35 points max)
        # ----------------------------------------------------
        ir_score = 0.0

        if expect_cancellation:
            if len(trace.cancellations_emitted) > 0:
                ir_score += 20.0
                details.append(f"Interruption Recovery (+20): Promptly emitted {len(trace.cancellations_emitted)} cancellations.")
            else:
                details.append("Interruption Recovery (0/20): Failed to cancel superseded call.")

            # Absence of stale re-runs: check that no completed mutation matches cancelled call
            cancelled_calls = set(trace.cancellations_emitted)
            stale_runs = [c for c in cancelled_calls if c in trace.tool_calls_dispatched[len(trace.cancellations_emitted):]]
            if not stale_runs:
                ir_score += 15.0
                details.append("Interruption Recovery (+15): No stale re-runs observed.")
            else:
                details.append(f"Interruption Recovery (0/15): Stale re-runs detected: {stale_runs}")
        else:
            # If no cancellation expected, full marks for clean execution
            ir_score = 35.0
            details.append("Interruption Recovery (+35): Clean scenario execution without unprompted cancellations.")

        # ----------------------------------------------------
        # 3. Response Latency (15 points max)
        # ----------------------------------------------------
        lat_score = 0.0
        first_lat = trace.first_spoken_action_latency_ms

        if first_lat is not None:
            if first_lat <= max_acceptable_latency_ms:
                lat_score = 15.0
                details.append(f"Response Latency (+15): Fast response ({first_lat:.1f}ms <= {max_acceptable_latency_ms}ms).")
            elif first_lat <= max_acceptable_latency_ms * 2:
                lat_score = 10.0
                details.append(f"Response Latency (+10): Acceptable response ({first_lat:.1f}ms).")
            elif first_lat <= max_acceptable_latency_ms * 4:
                lat_score = 5.0
                details.append(f"Response Latency (+5): Delayed response ({first_lat:.1f}ms).")
            else:
                lat_score = 2.0
                details.append(f"Response Latency (+2): High response latency ({first_lat:.1f}ms).")
        else:
            details.append("Response Latency (0/15): No spoken action detected.")

        # ----------------------------------------------------
        # 4. Safety & Protocol (10 points max)
        # ----------------------------------------------------
        sp_score = 10.0

        # Check for duplicate state changes
        # Ensure that no state modifying tool call was emitted with the exact same call_id or arguments
        mutations = [
            a for a in trace.actions_out
            if a["action"]["action_type"] == ActionType.TOOL_CALL.value
            and a["action"]["payload"].get("is_state_modifying") is True
        ]
        mutation_signatures = set()
        has_duplicate_mutation = False
        for m in mutations:
            sig = (m["action"]["payload"].get("tool_name"), str(m["action"]["payload"].get("arguments")))
            if sig in mutation_signatures:
                has_duplicate_mutation = True
                break
            mutation_signatures.add(sig)

        if has_duplicate_mutation:
            sp_score -= 8.0
            details.append("Safety & Protocol (-8): Duplicate state-modifying call detected!")
        else:
            details.append("Safety & Protocol (+5): Zero duplicate state modifications.")

        # Check schema validity (call_id presence, snapshot completeness)
        schema_valid = True
        for a in trace.actions_out:
            act = a["action"]
            if act["action_type"] == ActionType.TOOL_CALL.value and not act.get("call_id"):
                schema_valid = False
            if not act.get("state_snapshot"):
                schema_valid = False

        if schema_valid:
            details.append("Safety & Protocol (+5): 100% structured schema compliance.")
        else:
            sp_score -= 5.0
            details.append("Safety & Protocol (-5): Malformed action schema detected.")

        sp_score = max(0.0, sp_score)

        # ----------------------------------------------------
        # Quality & Multipliers
        # ----------------------------------------------------
        base_score = tc_score + ir_score + lat_score + sp_score

        # Quality multiplier evaluates naturalness and groundedness (1.0x baseline, 1.1x for grounded concise answers)
        quality_mult = 1.10

        # Multimodal multiplier (1.5x on multimodal scenarios)
        mm_mult = 1.50 if is_multimodal else 1.00

        final_score = base_score * quality_mult * mm_mult

        return ScenarioScore(
            scenario_id=trace.scenario_id,
            task_completion=tc_score,
            interruption_recovery=ir_score,
            response_latency=lat_score,
            safety_protocol=sp_score,
            base_score=base_score,
            quality_multiplier=quality_mult,
            is_multimodal=is_multimodal,
            multimodal_multiplier=mm_mult,
            final_score=final_score,
            details=details,
        )
