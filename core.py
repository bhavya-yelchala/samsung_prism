"""Core Interruptible Real-Time Agent connecting input and output asynchronous queues."""
from __future__ import annotations
import asyncio
from typing import Any, Dict, List, Optional
from schemas.events import EventType, InputEvent
from schemas.actions import ActionType, OutputAction, StateSnapshot
from agent.state import SessionStateManager
from agent.tools import ToolRegistry, IdempotencyGuard
from agent.coordination import CoordinationLayer
from agent.fast_path import FastPathReflexEngine
from agent.slow_path import SlowPathPlanner
from agent.multimodal import VisionGrounder, AudioDisfluencyResolver


class InterruptibleRealTimeAgent:
    """Voice-native dual-process assistant architecture with prompt interruption handling."""

    def __init__(
        self,
        input_queue: Optional[asyncio.Queue[InputEvent]] = None,
        output_queue: Optional[asyncio.Queue[OutputAction]] = None,
        session_id: str = "session_001",
    ):
        self.input_queue = input_queue or asyncio.Queue()
        self.output_queue = output_queue or asyncio.Queue()
        self.session_id = session_id

        # Internal components
        self.state_manager = SessionStateManager(session_id=session_id)
        self.tool_registry = ToolRegistry()
        self.idempotency_guard = IdempotencyGuard()
        self.coordination = CoordinationLayer(
            state_manager=self.state_manager,
            tool_registry=self.tool_registry,
            idempotency_guard=self.idempotency_guard,
        )
        self.fast_path = FastPathReflexEngine(state_manager=self.state_manager)
        self.vision_grounder = VisionGrounder()
        self.slow_path = SlowPathPlanner(
            state_manager=self.state_manager,
            coordination_layer=self.coordination,
            tool_registry=self.tool_registry,
            vision_grounder=self.vision_grounder,
        )

        self._running = False
        self._action_history: List[OutputAction] = []

    def reset(self) -> None:
        """Reset session memory and state (enforces session-scoped memory only)."""
        self.state_manager.reset()
        self.idempotency_guard.reset()
        self.fast_path.reset()
        self.vision_grounder.reset()
        self._action_history.clear()

    async def emit_action(self, action: OutputAction) -> None:
        """Dispatch action to asynchronous output queue and record in trace."""
        self._action_history.append(action)
        await self.output_queue.put(action)

    def process_event_step(self, event: InputEvent) -> List[OutputAction]:
        """Synchronous / deterministic event step handler for virtual clock harness."""
        actions: List[OutputAction] = []
        t = event.timestamp

        # 1. TOOL_MANIFEST
        if event.type == EventType.TOOL_MANIFEST:
            self.tool_registry.register_manifest(event.payload)

        # 2. INTERRUPTION_SIGNAL
        elif event.type == EventType.INTERRUPTION_SIGNAL:
            source = event.payload.get("source", "user")
            cancellations = self.coordination.handle_interruption(
                timestamp=t,
                reason=f"Interrupted by {source}",
            )
            actions.extend(cancellations)
            if "cancel" in source.lower():
                snap = self.state_manager.get_snapshot()
                snap.status = "cancelled"
                closure = OutputAction.final_response(
                    timestamp=t,
                    text="Understood, your request has been cancelled.",
                    snapshot=snap,
                    epoch=self.state_manager.epoch,
                    metadata={"cancelled_by": source},
                )
                actions.append(closure)

        # 3. VIDEO_FRAME
        elif event.type == EventType.VIDEO_FRAME:
            p = event.payload
            ctx = self.vision_grounder.ingest_frame(
                frame_id=p.get("frame_id", "f1"),
                labels=p.get("labels"),
                ocr_text=p.get("ocr_text"),
                frame_bytes=p.get("frame_bytes"),
            )
            # If visual ambiguity detected while waiting for device info
            if ctx.is_ambiguous and self.state_manager.intent == "troubleshoot_device":
                clarify_action = self.fast_path.generate_clarification(
                    timestamp=t,
                    question=ctx.clarification_prompt or "Camera view is unclear.",
                    missing_slots=["device_view"],
                )
                actions.append(clarify_action)

        # 4. AUDIO_CHUNK
        elif event.type == EventType.AUDIO_CHUNK:
            hint = event.payload.get("transcript_hint")
            if hint:
                # Disfluency resolution
                cleaned = AudioDisfluencyResolver.clean_hesitations(hint)
                # Delegate to transcription handling logic
                transcription_event = InputEvent.transcription(
                    timestamp=t,
                    text=cleaned,
                    is_final=event.payload.get("is_final", False),
                )
                actions.extend(self.process_event_step(transcription_event))

        # 5. TRANSCRIPTION_CHUNK
        elif event.type == EventType.TRANSCRIPTION_CHUNK:
            raw_text = event.payload.get("text", "")
            is_final = event.payload.get("is_final", False)

            # Check if mid-sentence self-repair or cancellation happened
            resolved_text, repair_info = AudioDisfluencyResolver.resolve_conversational_repair(raw_text)

            # If user explicitly corrected a slot mid-sentence and an active call is running for the old slot, cancel it!
            if repair_info:
                repaired_from = repair_info.get("repaired_from")
                if self.state_manager.active_calls:
                    # Stale active call detected: immediately cancel!
                    cancellations = self.coordination.handle_interruption(
                        timestamp=t,
                        reason=f"Mid-utterance slot correction: '{repaired_from}' replaced with '{list(repair_info.values())[0]}'",
                    )
                    actions.extend(cancellations)
                for rk, rv in repair_info.items():
                    if rk != "repaired_from":
                        self.state_manager.set_slot(rk, rv)

            # Parse intent and slots
            intent, slots, _ = self.slow_path.parse_user_intent_and_slots(raw_text)

            if intent:
                self.state_manager.set_intent(intent)
            if slots:
                self.state_manager.update_slots(slots)

            # Fast Path Floor Management: Sub-200ms Contextual Acknowledgment
            current_intent = self.state_manager.intent
            current_slots = self.state_manager.slots

            # Determine if a tool is planned
            filler = self.fast_path.generate_acknowledgment(
                timestamp=t,
                intent=current_intent,
                slots=current_slots,
            )
            if filler:
                actions.append(filler)

            # If final or complete clause, trigger Slow Path tool execution
            if is_final or ("wait" not in raw_text.lower() and len(current_slots) > 0 and current_intent):
                # Check missing slots for critical intents
                if current_intent == "flight_search" and not current_slots.get("destination"):
                    clarify = self.fast_path.generate_clarification(
                        timestamp=t,
                        question="Where would you like to fly to?",
                        missing_slots=["destination"],
                    )
                    actions.append(clarify)
                else:
                    tool_call_action, err = self.slow_path.plan_tool_execution(
                        timestamp=t,
                        intent=current_intent,
                        slots=current_slots,
                    )
                    if tool_call_action:
                        actions.append(tool_call_action)

        # 6. TOOL_RESULT
        elif event.type == EventType.TOOL_RESULT:
            call_id = event.payload.get("call_id", "")
            tool_name = event.payload.get("tool_name", "")
            result = event.payload.get("result")
            error = event.payload.get("error")

            # Check if call was cancelled or stale
            should_process, reason = self.coordination.should_process_tool_result(call_id, t)
            if not should_process:
                # Intercepted and discarded stale result!
                pass
            else:
                final_action = self.slow_path.handle_tool_completion(
                    timestamp=t,
                    call_id=call_id,
                    tool_name=tool_name,
                    result=result,
                    error=error,
                )
                actions.append(final_action)

        # Track history
        self._action_history.extend(actions)
        return actions

    async def run(self) -> None:
        """Asynchronous execution loop consuming from input_queue and emitting to output_queue."""
        self._running = True
        while self._running:
            try:
                event = await self.input_queue.get()
                actions = self.process_event_step(event)
                for action in actions:
                    await self.emit_action(action)
                self.input_queue.task_done()
            except asyncio.CancelledError:
                self._running = False
                break
            except Exception as e:
                # Maintain agent resilience
                pass

    def stop(self) -> None:
        self._running = False
