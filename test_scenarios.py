"""Public Test Suite: Nine Canonical Scenarios covering Text, Audio, and Visual modalities."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional
from events import EventType, InputEvent
from mock_env import MockEnvironment


@dataclass
class CanonicalScenario:
    scenario_id: str
    title: str
    modality: str  # text, audio, visual
    description: str
    events: List[InputEvent]
    expected_intent: Optional[str] = None
    expected_slots: Optional[Dict[str, Any]] = None
    expect_cancellation: bool = False
    configure_env: Optional[Callable[[MockEnvironment], None]] = None


def get_standard_manifest_event() -> InputEvent:
    """Standard scenario tool manifest."""
    tools = [
        {
            "name": "flight_search",
            "description": "Search available flights for destination and date.",
            "is_state_modifying": False,
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "origin": {"type": "string"},
                    "date": {"type": "string"},
                },
                "required": ["destination"],
            },
        },
        {
            "name": "book_flight",
            "description": "Book a specific flight seat (State Modifying).",
            "is_state_modifying": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "destination": {"type": "string"},
                    "flight_id": {"type": "string"},
                    "passengers": {"type": "integer"},
                },
                "required": ["destination"],
            },
        },
        {
            "name": "create_ticket",
            "description": "Create a customer support ticket (State Modifying).",
            "is_state_modifying": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["description"],
            },
        },
        {
            "name": "lookup_manual",
            "description": "Look up diagnostic troubleshooting solutions in device manuals.",
            "is_state_modifying": False,
            "parameters": {
                "type": "object",
                "properties": {
                    "device": {"type": "string"},
                    "error_code": {"type": "string"},
                    "symptom": {"type": "string"},
                },
                "required": ["device"],
            },
        },
    ]
    return InputEvent.tool_manifest(timestamp=0.0, tools=tools)


def build_scenario_1_text_interruption_flight() -> CanonicalScenario:
    """Scenario 1 (Text): Mid-sentence destination correction."""
    events = [
        get_standard_manifest_event(),
        # User starts requesting flight to Chicago
        InputEvent.transcription(timestamp=100.0, text="Find me flights to Chicago on 2026-10-15", is_final=False),
        # Agent starts tool call at ~100ms (latency is 600ms, would complete at 700ms)
        # User interrupts at t=350ms with destination correction
        InputEvent.interruption(timestamp=350.0, source="user_speech"),
        InputEvent.transcription(timestamp=360.0, text="Wait, make that Boston instead", is_final=True),
    ]
    return CanonicalScenario(
        scenario_id="SCENARIO_01_TEXT_INTERRUPT_FLIGHT",
        title="Flight Search Mid-Utterance Correction",
        modality="text",
        description="User initiates flight search to Chicago, then corrects destination to Boston mid-execution.",
        events=events,
        expected_intent="flight_search",
        expected_slots={"destination": "Boston", "date": "2026-10-15"},
        expect_cancellation=True,
    )


def build_scenario_2_text_cancel_booking() -> CanonicalScenario:
    """Scenario 2 (Text): Booking cancellation mid-execution to verify double-booking prevention."""
    events = [
        get_standard_manifest_event(),
        InputEvent.transcription(timestamp=100.0, text="Please book flight to Boston for me", is_final=True),
        # book_flight has latency 900ms -> would finish at 1000ms
        # User cancels booking at t=300ms
        InputEvent.interruption(timestamp=300.0, source="user_cancel"),
    ]
    return CanonicalScenario(
        scenario_id="SCENARIO_02_TEXT_CANCEL_BOOKING",
        title="State-Modifying Booking Interruption & Safety",
        modality="text",
        description="Booking initiated, then abruptly cancelled mid-flight. Asserts prompt cancellation and zero mutations.",
        events=events,
        expected_intent="book_flight",
        expected_slots={"destination": "Boston"},
        expect_cancellation=True,
    )


def build_scenario_3_text_chained_calls() -> CanonicalScenario:
    """Scenario 3 (Text): Multi-turn chained support ticket workflow."""
    events = [
        get_standard_manifest_event(),
        InputEvent.transcription(timestamp=100.0, text="I have a complaint, my baggage was delayed", is_final=True),
    ]
    return CanonicalScenario(
        scenario_id="SCENARIO_03_TEXT_CHAINED_TICKET",
        title="Customer Support Ticket Creation",
        modality="text",
        description="Processes customer support issue and triggers ticket creation workflow.",
        events=events,
        expected_intent="create_ticket",
        expected_slots={"category": "customer_support"},
        expect_cancellation=False,
    )


def build_scenario_4_text_fault_injection() -> CanonicalScenario:
    """Scenario 4 (Text): Tool fault injection handling and recovery."""
    def inject_fault(env: MockEnvironment):
        env.set_fault("flight_search", "503 Service Unavailable: Airline GDS timeout", count=1)

    events = [
        get_standard_manifest_event(),
        InputEvent.transcription(timestamp=100.0, text="Search flights to Chicago", is_final=True),
    ]
    return CanonicalScenario(
        scenario_id="SCENARIO_04_TEXT_FAULT_INJECTION",
        title="Tool Fault Injection & Graceful Handling",
        modality="text",
        description="External tool fails with 503 error; agent must catch and communicate without crashing.",
        events=events,
        expected_intent="flight_search",
        expected_slots={"destination": "Chicago"},
        expect_cancellation=False,
        configure_env=inject_fault,
    )


def build_scenario_5_text_unseen_tool() -> CanonicalScenario:
    """Scenario 5 (Text): Dynamic unseen tool manifest."""
    unseen_tool = {
        "name": "car_rental_reservation",
        "description": "Reserve a rental car at specified location.",
        "is_state_modifying": True,
        "parameters": {
            "type": "object",
            "properties": {
                "location": {"type": "string"},
                "days": {"type": "integer"},
            },
            "required": ["location"],
        },
    }
    events = [
        InputEvent.tool_manifest(timestamp=0.0, tools=[unseen_tool]),
        InputEvent.transcription(timestamp=100.0, text="Please execute car_rental_reservation location Denver", is_final=True),
    ]
    return CanonicalScenario(
        scenario_id="SCENARIO_05_TEXT_UNSEEN_TOOL",
        title="Dynamic Unseen Tool Ingestion & Execution",
        modality="text",
        description="Agent ingests previously unseen tool manifest dynamically and executes compliant tool call.",
        events=events,
        expected_intent="car_rental_reservation",
        expected_slots={"location": "Denver"},
        expect_cancellation=False,
    )


def build_scenario_6_audio_speech_hesitations() -> CanonicalScenario:
    """Scenario 6 (Audio): Speech hesitations and conversational self-repairs."""
    events = [
        get_standard_manifest_event(),
        InputEvent.audio_chunk(
            timestamp=100.0,
            duration_ms=400.0,
            is_final=True,
            transcript_hint="Um, uh, find flights to Seattle on 2026-10-15... no, two tickets to Seattle",
        ),
    ]
    return CanonicalScenario(
        scenario_id="SCENARIO_06_AUDIO_HESITATION_REPAIR",
        title="Audio Disfluency & Speech Self-Repair",
        modality="audio",
        description="Filters speech hesitations (um, uh) and resolves self-repair in audio stream.",
        events=events,
        expected_intent="flight_search",
        expected_slots={"destination": "Seattle", "date": "2026-10-15"},
        expect_cancellation=False,
    )


def build_scenario_7_audio_mid_speech_interruption() -> CanonicalScenario:
    """Scenario 7 (Audio): Interruption while agent is holding floor."""
    events = [
        get_standard_manifest_event(),
        InputEvent.audio_chunk(timestamp=100.0, duration_ms=200.0, transcript_hint="Find flights to Denver", is_final=True),
        # Interruption happens at 250ms while agent is executing
        InputEvent.interruption(timestamp=250.0, source="user_speech_barge_in"),
        InputEvent.audio_chunk(timestamp=300.0, duration_ms=200.0, transcript_hint="Stop, search flights to Miami instead", is_final=True),
    ]
    return CanonicalScenario(
        scenario_id="SCENARIO_07_AUDIO_BARGE_IN",
        title="Audio Barge-In Interruption & Re-Planning",
        modality="audio",
        description="User barges in with speech interruption; agent cancels active search and re-plans for Miami.",
        events=events,
        expected_intent="flight_search",
        expected_slots={"destination": "Miami"},
        expect_cancellation=True,
    )


def build_scenario_8_visual_ambiguity_clarification() -> CanonicalScenario:
    """Scenario 8 (Visual): Device troubleshooting with visual ambiguity check."""
    events = [
        get_standard_manifest_event(),
        # Ambiguous frame (empty labels and text)
        InputEvent.video_frame(timestamp=50.0, frame_id="frame_01", labels=[], ocr_text=""),
        InputEvent.transcription(timestamp=100.0, text="How do I troubleshoot this error?", is_final=True),
    ]
    return CanonicalScenario(
        scenario_id="SCENARIO_08_VISUAL_AMBIGUITY",
        title="Visual Ambiguity Clarification Request",
        modality="visual",
        description="Visual frame is obscured or missing; agent emits clarification request without hallucinating.",
        events=events,
        expected_intent="troubleshoot_device",
        expected_slots={},
        expect_cancellation=False,
    )


def build_scenario_9_visual_device_manual_lookup() -> CanonicalScenario:
    """Scenario 9 (Visual): Frame-grounded manual lookup."""
    events = [
        get_standard_manifest_event(),
        # Video frame clearly shows Samsung Smart TV with Error Code E-404
        InputEvent.video_frame(
            timestamp=50.0,
            frame_id="frame_tv_01",
            labels=["Samsung Smart TV"],
            ocr_text="System Network Alert. Error Code: E-404. Connection Dropped.",
        ),
        InputEvent.transcription(timestamp=100.0, text="Fix this error on my television", is_final=True),
    ]
    return CanonicalScenario(
        scenario_id="SCENARIO_09_VISUAL_MANUAL_LOOKUP",
        title="Frame-Grounded Manual Lookup & Diagnostics",
        modality="visual",
        description="Extracts error code E-404 from camera frame OCR and executes manual lookup tool.",
        events=events,
        expected_intent="troubleshoot_device",
        expected_slots={"device": "Samsung Smart TV", "error_code": "E-404"},
        expect_cancellation=False,
    )


def get_all_canonical_scenarios() -> List[CanonicalScenario]:
    return [
        build_scenario_1_text_interruption_flight(),
        build_scenario_2_text_cancel_booking(),
        build_scenario_3_text_chained_calls(),
        build_scenario_4_text_fault_injection(),
        build_scenario_5_text_unseen_tool(),
        build_scenario_6_audio_speech_hesitations(),
        build_scenario_7_audio_mid_speech_interruption(),
        build_scenario_8_visual_ambiguity_clarification(),
        build_scenario_9_visual_device_manual_lookup(),
    ]
