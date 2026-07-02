"""KNX DPT parsing helpers."""

from __future__ import annotations

import re
from typing import Any

_DPT_INFO_RE = re.compile(r"DPT\s+(\d+)\.(\d+)")


def parse_dpt_from_info(info: str | None) -> str | None:
    """Extract a DPT string from an Atios-style info field."""
    if not info:
        return None

    match = _DPT_INFO_RE.search(info)
    if match:
        return normalize_dpt(f"{match.group(1)}.{match.group(2)}")

    if "irrelevant" in info.lower():
        return "1.001"

    return None


def numeric_dpt_to_str(value: Any) -> str:
    """Convert numeric DPT values like 1001 or 5001 to KNX DPT strings."""
    text = str(value).strip()
    if not text:
        raise ValueError("DPT value is empty")

    if "." in text:
        return normalize_dpt(text)

    if not text.isdigit():
        raise ValueError(f"Invalid numeric DPT: {value!r}")

    if len(text) <= 3:
        return f"1.{int(text):03d}"

    return f"{int(text[:-3])}.{int(text[-3:]):03d}"


def normalize_dpt(value: Any) -> str:
    """Normalize a DPT value to '<main>.<sub>' with a 3-digit sub number."""
    text = str(value).strip()
    if "." not in text:
        return numeric_dpt_to_str(text)

    main, sub = text.split(".", 1)
    if not main.isdigit() or not sub.isdigit():
        raise ValueError(f"Invalid DPT: {value!r}")

    return f"{int(main)}.{int(sub):03d}"


def dpt_main_number(dpt: str) -> int:
    """Return the main DPT number."""
    normalized = normalize_dpt(dpt)
    return int(normalized.split(".", 1)[0])
