"""Guardia statica: il pacchetto non salva frame e non usa la rete."""

import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parent.parent / "focus_guard"

FORBIDDEN = [
    r"\bimwrite\b",
    r"\bVideoWriter\b",
    r"\bimport\s+(socket|requests|urllib|http|httpx|aiohttp)\b",
    r"\bfrom\s+(socket|requests|urllib|http|httpx|aiohttp)\b",
    r"\.save\(",  # es. QImage.save / PIL.Image.save
    r"\bnp\.save",
    r"\bpickle\b",
]


def test_no_frame_persistence_or_network_in_package():
    offenders = []
    for path in PACKAGE.rglob("*.py"):
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if any(re.search(p, line) for p in FORBIDDEN):
                offenders.append(f"{path.relative_to(PACKAGE)}:{lineno}: {line.strip()}")
    assert offenders == []
