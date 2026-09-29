"""Multimodal grounding for audio speech hesitations and video frame perception."""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class PerceivedVisualContext:
    frame_id: str
    detected_devices: List[str] = field(default_factory=list)
    error_codes: List[str] = field(default_factory=list)
    visual_text: str = ""
    is_ambiguous: bool = False
    clarification_prompt: Optional[str] = None


class VisionGrounder:
    """Grounds user queries into camera frames and device manuals."""

    def __init__(self):
        self.cached_frames: Dict[str, PerceivedVisualContext] = {}
        self.latest_frame_id: Optional[str] = None

    def reset(self) -> None:
        self.cached_frames.clear()
        self.latest_frame_id = None

    def ingest_frame(
        self,
        frame_id: str,
        labels: Optional[List[str]] = None,
        ocr_text: Optional[str] = None,
        frame_bytes: Optional[bytes] = None,
    ) -> PerceivedVisualContext:
        """Process incoming video frame and extract key semantic features."""
        labels = labels or []
        ocr_text = ocr_text or ""

        # Extract error codes via regex from OCR
        error_matches = re.findall(r"(?:error[\s_]*code|code|err)[\s:\-_=]*([A-Z0-9\-_]+)", ocr_text, re.IGNORECASE)
        error_codes = [c for c in error_matches if c.lower() not in ("code", "error", "alert", "dropped")]
        error_codes = list(dict.fromkeys(error_codes))

        # Check for ambiguity (e.g. empty labels and no text)
        is_ambiguous = len(labels) == 0 and len(ocr_text.strip()) == 0

        context = PerceivedVisualContext(
            frame_id=frame_id,
            detected_devices=labels,
            error_codes=error_codes,
            visual_text=ocr_text,
            is_ambiguous=is_ambiguous,
            clarification_prompt="The camera view is unclear or obstructed. Please point your camera directly at the device display or LED indicator." if is_ambiguous else None,
        )
        self.cached_frames[frame_id] = context
        self.latest_frame_id = frame_id
        return context

    def get_latest_context(self) -> Optional[PerceivedVisualContext]:
        if self.latest_frame_id and self.latest_frame_id in self.cached_frames:
            return self.cached_frames[self.latest_frame_id]
        return None

    def ground_device_query(
        self,
        query: str,
        frame_context: Optional[PerceivedVisualContext] = None,
    ) -> Dict[str, Any]:
        """Extract tool arguments for device troubleshooting from query + frame."""
        ctx = frame_context or self.get_latest_context()
        slots: Dict[str, Any] = {}

        if ctx:
            if ctx.detected_devices:
                slots["device"] = ctx.detected_devices[0]
            if ctx.error_codes:
                slots["error_code"] = ctx.error_codes[0]
            if "flashing" in query.lower() or "led" in query.lower() or "blinking" in query.lower():
                slots["symptom"] = "blinking_indicator"
            elif "wifi" in query.lower() or "network" in query.lower():
                slots["symptom"] = "network_connection_failure"

        return slots


class AudioDisfluencyResolver:
    """Resolves conversational self-repairs, hesitations, and false starts in audio speech."""

    # Disfluency / hesitation fillers
    FILLERS = [r"\bum\b", r"\buh\b", r"\ber\b", r"\bah\b", r"\bhmm\b", r"\blike\b", r"\byou know\b"]
    # Self-repair cue phrases
    REPAIR_CUES = [
        r"wait[,\s]+(?:make that|actually|no)?",
        r"actually[,\s]+",
        r"no[,\s]+(?:make that|rather)?",
        r"scratch that[,\s]*",
        r"instead of [a-zA-Z\s]+[,\s]+(?:make that|use)?",
    ]

    @classmethod
    def clean_hesitations(cls, text: str) -> str:
        """Remove spoken hesitations while preserving semantic content."""
        cleaned = text
        for pat in cls.FILLERS:
            cleaned = re.sub(pat, "", cleaned, flags=re.IGNORECASE)
        # Collapse whitespace
        return re.sub(r"\s+", " ", cleaned).strip()

    @classmethod
    def resolve_conversational_repair(cls, text: str) -> Tuple[str, Optional[Dict[str, str]]]:
        """Detect and resolve mid-utterance self-repairs.

        Example: 'Book a flight to Chicago- wait, make that Boston' -> ('Book a flight to Boston', {'destination': 'Boston', 'repaired_from': 'Chicago'})
        """
        # Clean hesitations first
        text = cls.clean_hesitations(text)

        # Check self-repair patterns
        # Pattern 1: "... to <CityA> ... wait, make that <CityB>"
        repair_pattern = re.search(
            r"(?:to|for)\s+([A-Za-z\s]+?)(?:[-–—\s]+|\s+)(?:wait|actually|no|scratch that)[,\s]+(?:make that|rather)?\s*([A-Za-z\s]+)",
            text,
            re.IGNORECASE,
        )
        if repair_pattern:
            old_val = repair_pattern.group(1).strip()
            new_val = repair_pattern.group(2).strip()
            resolved_text = text[:repair_pattern.start()] + f"to {new_val}"
            return resolved_text.strip(), {"destination": new_val, "repaired_from": old_val}

        # Pattern 1b: Standalone correction "Wait, make that Boston instead"
        standalone_repair = re.search(
            r"(?:wait|actually|no|scratch that)[,\s]+(?:make that|change to|rather)\s+([A-Za-z\s]+?)(?:\s+instead|\.|$)",
            text,
            re.IGNORECASE,
        )
        if standalone_repair:
            new_val = standalone_repair.group(1).strip()
            return f"to {new_val}", {"destination": new_val}

        # Pattern 2: "... <NumA> tickets ... no <NumB> tickets"
        count_repair = re.search(
            r"(\d+|one|two|three|four|five)\s+tickets?[\s,]+(?:no|actually|wait)[,\s]+(?:make that)?\s*(\d+|one|two|three|four|five)\s+tickets?",
            text,
            re.IGNORECASE,
        )
        if count_repair:
            old_num = count_repair.group(1).strip()
            new_num = count_repair.group(2).strip()
            resolved_text = text[:count_repair.start()] + f"{new_num} tickets" + text[count_repair.end():]
            return resolved_text.strip(), {"ticket_count": new_num, "repaired_from": old_num}

        return text, None
