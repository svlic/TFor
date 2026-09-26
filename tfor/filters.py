from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class MessageFields:
    text: str = ""
    sender_name: str = ""
    sender_username: str = ""
    sender_id: int | None = None


def _matches(candidate: str, value: str, mode: str) -> bool:
    if mode == "contains":
        return value.casefold() in candidate.casefold()
    if mode == "exact":
        return value.casefold() == candidate.casefold()
    if mode == "regex":
        try:
            return re.search(value, candidate, re.IGNORECASE) is not None
        except re.error:
            return False
    return False


def evaluate_filters(steps: list[dict[str, Any]], fields: MessageFields) -> tuple[bool, list[dict[str, Any]]]:
    results: list[dict[str, Any]] = []
    for step in steps:
        if not step.get("enabled", True):
            continue
        candidate = str(getattr(fields, step["field"]) or "")
        hit = any(_matches(candidate, str(value), step["match_mode"]) for value in step["values"])
        passed = not hit if step["kind"] == "blacklist" else hit
        results.append(
            {
                "step_id": step.get("id"),
                "position": step.get("position"),
                "kind": step["kind"],
                "field": step["field"],
                "match_mode": step["match_mode"],
                "outcome": "PASS" if passed else "REJECT",
            }
        )
        if not passed:
            return False, results
    return True, results


def classify_media(message: Any) -> str | None:
    if not getattr(message, "media", None):
        return None
    if getattr(message, "photo", None):
        return "photo"
    if getattr(message, "video", None):
        return "video"
    if getattr(message, "voice", None):
        return "voice"
    if getattr(message, "audio", None):
        return "audio"
    if getattr(message, "document", None):
        return "document"
    return "other"
