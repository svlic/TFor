from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any


# Unicode Default_Ignorable_Code_Point ranges, including reserved tag/selector
# code points. Do not strip all marks: accents and vowel signs carry meaning.
_IGNORABLE_RANGES = (
    (0x00AD, 0x00AD), (0x034F, 0x034F), (0x061C, 0x061C),
    (0x115F, 0x1160), (0x17B4, 0x17B5), (0x180B, 0x180F),
    (0x200B, 0x200F), (0x202A, 0x202E), (0x2060, 0x206F),
    (0x3164, 0x3164), (0xFE00, 0xFE0F), (0xFEFF, 0xFEFF),
    (0xFFA0, 0xFFA0), (0xFFF0, 0xFFF8), (0x1BCA0, 0x1BCA3),
    (0x1D173, 0x1D17A), (0xE0000, 0xE0FFF),
)
_IGNORABLE_TRANSLATION = dict.fromkeys(
    code for start, end in _IGNORABLE_RANGES for code in range(start, end + 1)
)
_IGNORABLE_TRANSLATION.update(dict.fromkeys(
    code for code in (*range(0x20), *range(0x7F, 0xA0)) if not chr(code).isspace()
))


def _normalize_for_matching(text: str) -> str:
    # Remove fillers before NFKC can turn them into ordinary script characters,
    # and join separated combining sequences before canonical composition.
    return unicodedata.normalize("NFKC", text.translate(_IGNORABLE_TRANSLATION))


@dataclass(slots=True)
class MessageFields:
    text: str = ""
    sender_name: str = ""
    sender_username: str = ""
    sender_id: int | None = None


def _matches(candidate: str, value: str, mode: str) -> bool:
    if mode in ("contains", "exact"):
        value = _normalize_for_matching(value)
        # An invisible-only literal must not become a match-all empty string.
        if not value:
            return False
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
        candidate = _normalize_for_matching(str(getattr(fields, step["field"]) or ""))
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
