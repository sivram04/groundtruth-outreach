"""The system sends email from exactly one place, and only through a sanctioned path.

Historically the system never sent at all. It now has two sanctioned callers of the one send
path (``outreach/send.py``): the console's human-clicked "Approve and send", and the scheduled
``outreach/auto_send.py`` job, which sends only already-created, already-approved drafts, up to
the daily cap, re-checking the call log and suppression list at send time (founder decision,
2026-10-08: "owner's 5-feature roadmap" item 3). These tests pin that pair down instead of
forbidding sending outright:

  * a message-send call may appear only in ``outreach/send.py`` (and nowhere else);
  * SMTP and the send-only Gmail scope never appear anywhere;
  * only the console and ``outreach/auto_send.py`` import ``outreach/send.py`` - no other worker
    job or scheduled job does, so the rest of the automation can create drafts but can never send.
"""

import re
from pathlib import Path

CODE = Path(__file__).resolve().parent.parent / "outreach"
SEND_MODULE = "send.py"

# Patterns that must never appear anywhere in outreach/.
FORBIDDEN_EVERYWHERE = [
    r"smtplib",
    r"SMTP\s*\(",
    r"gmail\.send",   # the send-only scope; the system uses gmail.compose and sends drafts
    r"sendmail",
]
# A message/draft send call is allowed only in the one sanctioned module.
SEND_CALL = r"\.send\s*\("


def test_no_smtp_or_send_scope_anywhere():
    hits = []
    for path in CODE.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_EVERYWHERE:
            for m in re.finditer(pattern, text):
                line = text.count("\n", 0, m.start()) + 1
                hits.append(f"{path.name}:{line} matches {pattern}")
    assert not hits, "Forbidden sending code found:\n" + "\n".join(hits)


def test_a_send_call_appears_only_in_the_sanctioned_module():
    hits = []
    for path in CODE.rglob("*.py"):
        if path.name == SEND_MODULE:
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(SEND_CALL, text):
            line = text.count("\n", 0, m.start()) + 1
            hits.append(f"{path.name}:{line} has a send call outside {SEND_MODULE}")
    assert not hits, "A send call exists outside the sanctioned send module:\n" + "\n".join(hits)


def test_only_the_console_and_auto_send_import_the_send_module():
    # The rest of the automation (sync, follow-ups, drafting jobs, tracking) must never reach the
    # send path. Only the console (a human clicks Approve) and auto_send.py (the scheduled,
    # cap-limited drip of already-approved drafts) may import it.
    allowed = {SEND_MODULE, "console.py", "auto_send.py"}
    importers = []
    for path in CODE.rglob("*.py"):
        if path.name in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        if re.search(r"^\s*from outreach import .*\bsend\b", text, re.MULTILINE) or \
           re.search(r"^\s*import outreach\.send\b", text, re.MULTILINE) or \
           re.search(r"^\s*from outreach\.send import\b", text, re.MULTILINE):
            importers.append(path.name)
    assert not importers, "Modules other than the console import the send path:\n" + "\n".join(importers)
