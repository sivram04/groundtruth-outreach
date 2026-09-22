"""The system never sends email. This test fails the build if any sending path appears."""

import re
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent / "outreach"
FORBIDDEN = [
    r"\.send\s*\(",          # drafts().send(), messages().send()
    r"smtplib",
    r"SMTP\s*\(",
    r"gmail\.send",          # the send-only scope
    r"sendmail",
]


def test_no_sending_code():
    hits = []
    for path in CODE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN:
            for m in re.finditer(pattern, text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.name}:{line} matches {pattern}")
    assert not hits, "Sending code found:\n" + "\n".join(hits)
