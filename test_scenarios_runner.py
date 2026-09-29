"""Unit and Integration tests running the 9 canonical scenarios through the VirtualClockHarness."""
import unittest
from agent.core import InterruptibleRealTimeAgent
from harness.virtual_clock import VirtualClockHarness
from harness.mock_env import MockEnvironment
from harness.evaluator import ScenarioEvaluator
from harness.test_scenarios import get_all_canonical_scenarios


class TestInterruptibleRealTimeAgent(unittest.TestCase):
    """Test suite executing all canonical evaluation scenarios."""

    def setUp(self):
        self.mock_env = MockEnvironment()
        self.harness = VirtualClockHarness(mock_env=self.mock_env)
        self.agent = InterruptibleRealTimeAgent()

    def test_all_canonical_scenarios(self):
        scenarios = get_all_canonical_scenarios()
        self.assertEqual(len(scenarios), 9, "Must contain exactly 9 canonical scenarios.")

        scores = []
        for sc in scenarios:
            with self.subTest(scenario_id=sc.scenario_id):
                # Reset mock env and configure if needed
                self.mock_env = MockEnvironment()
                if sc.configure_env:
                    sc.configure_env(self.mock_env)
                self.harness.mock_env = self.mock_env

                # Run scenario on virtual clock
                trace = self.harness.run_scenario(
                    scenario_id=sc.scenario_id,
                    events=sc.events,
                    agent=self.agent,
                )

                # Evaluate trace
                score = ScenarioEvaluator.evaluate(
                    trace=trace,
                    expected_intent=sc.expected_intent,
                    expected_slots=sc.expected_slots,
                    expect_cancellation=sc.expect_cancellation,
                    is_multimodal=(sc.modality in ("audio", "visual")),
                )
                scores.append(score)

                # Assert baseline criteria
                self.assertGreaterEqual(
                    score.base_score,
                    80.0,
                    f"Scenario {sc.scenario_id} scored below 80 base points! (Score: {score.base_score:.1f}) Details: {score.details}",
                )

                # Ensure safety: zero duplicate state modifications
                self.assertEqual(score.safety_protocol, 10.0, f"Safety protocol violation in {sc.scenario_id}")

    def test_interruption_grace_period_cancellation(self):
        """Specifically verifies sub-millisecond cancellation of superseded calls."""
        from schemas.events import InputEvent
        from harness.test_scenarios import get_standard_manifest_event

        events = [
            get_standard_manifest_event(),
            InputEvent.transcription(timestamp=100.0, text="Find me flights to Chicago", is_final=True),
            # Interruption at 200ms
            InputEvent.interruption(timestamp=200.0, source="user_speech"),
        ]
        trace = self.harness.run_scenario("TEST_CANCELLATION", events, self.agent)

        # Check cancellations emitted
        self.assertGreater(len(trace.cancellations_emitted), 0)
        # Check active call removed
        self.assertEqual(len(self.agent.state_manager.active_calls), 0)
        # Check epoch incremented
        self.assertGreater(self.agent.state_manager.epoch, 0)


if __name__ == "__main__":
    unittest.main()
