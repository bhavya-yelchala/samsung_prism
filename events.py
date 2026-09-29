"""Input Event schemas for the real-time interruptible agent."""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional


class EventType(str, Enum):
    TRANSCRIPTION_CHUNK = "TRANSCRIPTION_CHUNK"
    AUDIO_CHUNK = "AUDIO_CHUNK"
    VIDEO_FRAME = "VIDEO_FRAME"
    INTERRUPTION_SIGNAL = "INTERRUPTION_SIGNAL"
    TOOL_RESULT = "TOOL_RESULT"
    TOOL_MANIFEST = "TOOL_MANIFEST"


@dataclass
class InputEvent:
    timestamp: float  # Virtual clock in milliseconds
    type: EventType
    payload: Dict[str, Any] = field(default_factory=dict)
    event_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "type": self.type.value if isinstance(self.type, Enum) else self.type,
            "payload": self.payload,
            "event_id": self.event_id,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict())

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> InputEvent:
        event_type = EventType(data["type"]) if isinstance(data["type"], str) else data["type"]
        return cls(
            timestamp=float(data["timestamp"]),
            type=event_type,
            payload=data.get("payload", {}),
            event_id=data.get("event_id"),
        )

    # Convenience constructors
    @classmethod
    def transcription(cls, timestamp: float, text: str, is_final: bool = False, confidence: float = 1.0) -> InputEvent:
        return cls(
            timestamp=timestamp,
            type=EventType.TRANSCRIPTION_CHUNK,
            payload={"text": text, "is_final": is_final, "confidence": confidence},
        )

    @classmethod
    def interruption(cls, timestamp: float, source: str = "user_speech") -> InputEvent:
        return cls(
            timestamp=timestamp,
            type=EventType.INTERRUPTION_SIGNAL,
            payload={"source": source, "interrupted_at": timestamp},
        )

    @classmethod
    def tool_result(
        cls,
        timestamp: float,
        call_id: str,
        tool_name: str,
        result: Any = None,
        error: Optional[str] = None,
        execution_time_ms: float = 0.0,
    ) -> InputEvent:
        return cls(
            timestamp=timestamp,
            type=EventType.TOOL_RESULT,
            payload={
                "call_id": call_id,
                "tool_name": tool_name,
                "result": result,
                "error": error,
                "execution_time_ms": execution_time_ms,
            },
        )

    @classmethod
    def tool_manifest(cls, timestamp: float, tools: List[Dict[str, Any]]) -> InputEvent:
        return cls(
            timestamp=timestamp,
            type=EventType.TOOL_MANIFEST,
            payload={"tools": tools},
        )

    @classmethod
    def audio_chunk(
        cls,
        timestamp: float,
        audio_bytes: Optional[bytes] = None,
        format: str = "wav",
        duration_ms: float = 200.0,
        is_final: bool = False,
        transcript_hint: Optional[str] = None,
    ) -> InputEvent:
        return cls(
            timestamp=timestamp,
            type=EventType.AUDIO_CHUNK,
            payload={
                "format": format,
                "duration_ms": duration_ms,
                "is_final": is_final,
                "transcript_hint": transcript_hint,
                "has_audio": audio_bytes is not None,
            },
        )

    @classmethod
    def video_frame(
        cls,
        timestamp: float,
        frame_id: str,
        format: str = "png",
        frame_bytes: Optional[bytes] = None,
        labels: Optional[List[str]] = None,
        ocr_text: Optional[str] = None,
    ) -> InputEvent:
        return cls(
            timestamp=timestamp,
            type=EventType.VIDEO_FRAME,
            payload={
                "frame_id": frame_id,
                "format": format,
                "labels": labels or [],
                "ocr_text": ocr_text or "",
                "has_bytes": frame_bytes is not None,
            },
        )
