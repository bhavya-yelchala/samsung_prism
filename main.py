"""CLI runner and evaluation dashboard for the Interruptible Real-Time Agent."""
from __future__ import annotations
import json
import sys
from typing import List
from agent.core import InterruptibleRealTimeAgent
from harness.virtual_clock import VirtualClockHarness
from harness.mock_env import MockEnvironment
from harness.evaluator import ScenarioEvaluator, ScenarioScore
from harness.test_scenarios import get_all_canonical_scenarios


def print_banner():
    banner = """
========================================================================================
   Samsung PRISM - Theme 05: Interruptible Real-Time Agents Evaluation Harness
   Dual-Process Architecture (Fast & Slow Paths) with Unified Timeline & State Snapshots
========================================================================================
"""
    print(banner)


def run_evaluation() -> List[ScenarioScore]:
    print_banner()
    scenarios = get_all_canonical_scenarios()
    agent = InterruptibleRealTimeAgent()
    results: List[ScenarioScore] = []

    print(f"Loaded {len(scenarios)} Canonical Evaluation Scenarios:")
    print("----------------------------------------------------------------------------------------")

    for idx, sc in enumerate(scenarios, 1):
        mock_env = MockEnvironment()
        if sc.configure_env:
            sc.configure_env(mock_env)

        harness = VirtualClockHarness(mock_env=mock_env)
        trace = harness.run_scenario(sc.scenario_id, sc.events, agent)

        score = ScenarioEvaluator.evaluate(
            trace=trace,
            expected_intent=sc.expected_intent,
            expected_slots=sc.expected_slots,
            expect_cancellation=sc.expect_cancellation,
            is_multimodal=(sc.modality in ("audio", "visual")),
        )
        results.append(score)

        print(f"\n[{idx}/9] {sc.title} ({sc.modality.upper()})")
        print(f"     ID: {sc.scenario_id}")
        print(f"     Virtual Duration: {trace.total_virtual_duration_ms:.1f}ms | First Spoken Latency: {trace.first_spoken_action_latency_ms or 0.0:.1f}ms")
        print(f"     Cancellations Emitted: {len(trace.cancellations_emitted)} | Tool Calls: {len(trace.tool_calls_dispatched)}")
        print(f"     Scores -> Task Comp: {score.task_completion:.1f}/40 | Interr Rec: {score.interruption_recovery:.1f}/35 | Latency: {score.response_latency:.1f}/15 | Safety: {score.safety_protocol:.1f}/10")
        print(f"     Base Score: {score.base_score:.1f}/100 | Quality: {score.quality_multiplier:.2f}x | Multimodal: {score.multimodal_multiplier:.2f}x")
        print(f"     FINAL WEIGHTED SCORE: {score.final_score:.2f}")

    # Summary table
    print("\n" + "=" * 90)
    print(f"{'#':<3} | {'Scenario Title':<35} | {'Modality':<8} | {'Base':<6} | {'Final':<7} | {'Status'}")
    print("-" * 90)

    total_final = 0.0
    for idx, (sc, score) in enumerate(zip(scenarios, results), 1):
        status = "PASSED (100+)" if score.final_score >= 100.0 else "PASSED"
        print(f"{idx:<3} | {sc.title[:35]:<35} | {sc.modality:<8} | {score.base_score:<6.1f} | {score.final_score:<7.1f} | {status}")
        total_final += score.final_score

    avg_score = total_final / len(results)
    print("=" * 90)
    print(f"OVERALL EVALUATION AVERAGE SCORE: {avg_score:.2f} / 100 (Weighted & Multiplied)")
    print("=" * 90 + "\n")
    return results


if __name__ == "__main__":
    run_evaluation()
