"""Made-up leads for the console: one of every kind of lead the pages have to show.

The React app's demo build and its tests read `console/src/demo/snapshot.json`, which is this
data passed through the real `console_model.build`, so the pages are always tested against the
shape the server really sends. Nothing here is a real company or person; every domain ends in
.test.

    python tests/console_fixture.py --write     # rewrite console/src/demo/snapshot.json
"""

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for path in (str(HERE), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from outreach import console_model, drafting, drafts, sequence  # noqa: E402
from outreach.sync import _event  # noqa: E402
from stage4_fakes import at, lead  # noqa: E402

FIXTURE = ROOT / "console" / "src" / "demo" / "snapshot.json"
NOW = at("2026-09-28 09:00")  # a Monday
SETTINGS = {"sender_email": "admin@lakshyaa.ai", "daily_cap": 4, "offer_approved": False,
            "tracking_enabled": False, "postal_address": "1 Made Up Road, Nowhere, OH 00000",
            "sender_phone": "+1 555 010 0000", "sender_name": "Demo Founder"}
HANDBOOK = "demo-handbook-document"


def person(lead_id, company, name, address, website, **changes):
    return lead(lead_id, Company=company, **{"BEST EMAIL": address, "Their email": address,
                                            "Decision maker": name, "Website": website,
                                            "Profile status": "READY", **changes})


def rows():
    return [
        # Emailed by hand; the first follow-up was due on Friday.
        person("A-0001", "Example Electric", "Sam Rivers", "sam@example-electric.test",
               "https://example-electric.test/", **{"Sent by hand": "2026-09-22"}),
        # Replied.
        person("A-0002", "Acme Plumbing", "Pat Lee", "pat@acme-plumbing.test",
               "https://acme-plumbing.test/", **{"Sent by hand": "2026-09-23"}),
        # Emailed on Friday: follow-up 1 comes up on Wednesday.
        person("A-0003", "Northside Mechanical", "Robin Hale", "robin@northside-mech.test",
               "https://northside-mech.test/", **{"Sent by hand": "2026-09-25"}),
        # Emailed at an address the row does not list: a match to check.
        person("A-0004", "Riverbend Drywall", "Dennis Ward", "dennis@riverbend-drywall.test",
               "riverbend-drywall.test", **{"Sent by hand": "2026-09-22"}),
        # Bounced.
        person("A-0005", "Harbor Glass", "Kim Ortiz", "kim@harbor-glass.test",
               "https://harbor-glass.test/", **{"Sent by hand": "2026-09-22"}),
        # Asked to stop.
        person("A-0006", "Summit Roofing", "Lee Park", "lee@summit-roofing.test",
               "https://summit-roofing.test/", **{"Sent by hand": "2026-09-22"}),
        # Ready for a first draft.
        person("A-0007", "Lakeside Concrete", "Jo Bennett", "jo@lakeside-concrete.test",
               "https://lakeside-concrete.test/"),
        person("A-0008", "Pioneer Paving", "Ali Moreno", "ali@pioneer-paving.test",
               "https://pioneer-paving.test/"),
        # Not ready, each for its own reason.
        person("A-0009", "Maple Masonry", "Chris Doyle", "chris@maple-masonry.test",
               "https://maple-masonry.test/",
               **{"Email check": "RISKY", "Reason": "catch-all domain"}),
        person("A-0010", "Cedar Homes", "Val Kemp", "val@cedar-homes.test",
               "https://cedar-homes.test/",
               **{"Fit": "DISQUALIFIED", "Fit reason": "2 quote(s) show residential work"}),
        person("A-0011", "Birch Landscaping", "Max Ruiz", "max@birch-landscaping.test",
               "https://birch-landscaping.test/", HOLD="waiting for an introduction"),
        # A website cell that must never become a link, and a name with markup in it.
        person("A-0012", "Oak Tile & Stone <b>Ltd</b>", "Ray Fox", "ray@oak-tile.test",
               "javascript:alert(1)", **{"Profile status": ""}),
        # Ready, but the writer found no quote good enough to open with.
        person("A-0013", "Granite Works", "Sky Adams", "sky@granite-works.test",
               "https://granite-works.test/"),
        # Ready, and not written yet.
        person("A-0014", "Cobalt Glass", "Rene Diaz", "rene@cobalt-glass.test",
               "https://cobalt-glass.test/"),
        # Phone-only: no email to draft, so the next action is a call, not a draft.
        lead("A-0015", Company="Redwood Plumbing", Website="https://redwood-plumbing.test/",
             **{"BEST EMAIL": "", "Their email": "", "Decision maker": "Sam Ford",
                "Phone": "(614) 555-0142", "Email check": "", "Fit": "", "Profile status": ""}),
        # Company-only: no email or phone yet, so the next action is to find a contact.
        lead("A-0016", Company="Cedar Roofing", Website="cedar-roofing.test",
             **{"BEST EMAIL": "", "Their email": "", "Decision maker": "", "Phone": "",
                "Email check": "", "Fit": "", "Profile status": ""}),
        # This system's tracked draft, sent, opened and clicked.
        person("B-0001", "Pine Electrical", "Dana Cole", "dana@pine-electrical.test",
               "https://pine-electrical.test/",
               **{"Draft status": "CREATED", "Draft action": "act-b1", "Draft ID": "draft-b1",
                  "Draft thread ID": "t-b1", "Draft tracked": "yes",
                  "Drafted at": "2026-09-24T13:00:00+00:00"}),
        # This system's draft, waiting in Gmail.
        person("B-0002", "Spruce HVAC", "Mo Grant", "mo@spruce-hvac.test",
               "https://spruce-hvac.test/",
               **{"Draft status": "CREATED", "Draft action": "act-b2", "Draft ID": "draft-b2",
                  "Draft thread ID": "t-b2", "Drafted at": "2026-09-27T14:30:00+00:00"}),
        # Nothing done yet.
        person("B-0003", "Aspen Siding", "Ari Lang", "ari@aspen-siding.test",
               "https://aspen-siding.test/",
               **{"Email check": "", "Fit": "", "Profile status": ""}),
    ]


def events():
    sent, replied, bounced = sequence.SENT, sequence.REPLIED, sequence.BOUNCED
    return [
        _event("A-0001", sent, "INITIAL", at("2026-09-22 13:18"), "sam@example-electric.test",
               "ADDRESS", "t-a1", "m-a1", "hand-written"),
        _event("A-0002", sent, "INITIAL", at("2026-09-23 10:00"), "pat@acme-plumbing.test",
               "ADDRESS", "t-a2", "m-a2", "hand-written"),
        _event("A-0002", replied, "", at("2026-09-24 16:40"), "pat@acme-plumbing.test",
               "THREAD", "t-a2", "m-a2r", ""),
        _event("A-0003", sent, "INITIAL", at("2026-09-25 11:05"), "robin@northside-mech.test",
               "ADDRESS", "t-a3", "m-a3", "hand-written"),
        _event("A-0004", sent, "UNCONFIRMED", at("2026-09-22 13:40"), "jeff@riverbend-drywall.test",
               "DOMAIN", "t-a4", "m-a4", "hand-written"),
        _event("A-0005", sent, "INITIAL", at("2026-09-22 14:02"), "kim@harbor-glass.test",
               "ADDRESS", "t-a5", "m-a5", "hand-written"),
        _event("A-0005", bounced, "", at("2026-09-22 14:03"), "kim@harbor-glass.test",
               "THREAD", "t-a5", "m-a5b", "5.1.1 address not found"),
        _event("A-0006", sent, "INITIAL", at("2026-09-22 14:30"), "lee@summit-roofing.test",
               "ADDRESS", "t-a6", "m-a6", "hand-written"),
        _event("A-0006", sequence.OPT_OUT, "", at("2026-09-23 08:15"), "lee@summit-roofing.test",
               "THREAD", "t-a6", "m-a6r", "no thanks"),
        _event("B-0001", sequence.DRAFTED, "INITIAL", at("2026-09-24 09:00"),
               "dana@pine-electrical.test", "DRAFT", "t-b1", "", "draft draft-b1, tracked",
               key="draft:act-b1"),
        _event("B-0001", sent, "INITIAL", at("2026-09-24 09:12"), "dana@pine-electrical.test",
               "DRAFT", "t-b1", "m-b1", ""),
        _event("B-0001", sequence.OPEN, "INITIAL", at("2026-09-24 10:30"),
               "dana@pine-electrical.test", "DRAFT", "t-b1", "", "Gmail", key="hit:b1-open"),
        _event("B-0001", sequence.CLICK, "INITIAL", at("2026-09-24 10:31"),
               "dana@pine-electrical.test", "DRAFT", "t-b1", "", "lakshyaa.ai",
               key="hit:b1-click"),
        _event("B-0002", sequence.DRAFTED, "INITIAL", at("2026-09-27 10:30"),
               "mo@spruce-hvac.test", "DRAFT", "t-b2", "", "draft draft-b2", key="draft:act-b2"),
        # A tracking test to the founder's own inbox: never a lead, never counted.
        _event("TEST", sent, "TEST", at("2026-09-28 08:00"), "founder@example.test", "DRAFT",
               "t-test", "m-test", "tracking test"),
    ]


def demo_body(first_name, company):
    """A made-up email's shape: the real words come from the handbook and the company's quote."""
    signature = ["Best,", "Demo Founder", "Founder, Demo Product", "https://example.test",
                 "1 Made Up Road, Nowhere, OH 00000", drafting.OPT_OUT]
    return "\n\n".join([
        f"Hi {first_name},",
        f"[One sentence about {company}, written only from the quote on its own site.]",
        "[The offer, in the handbook's words.]",
        "[One question, as the handbook asks it.]",
        "\n".join(signature)])


def draft_rows():
    def row(lead_id, company, to, first, status, why, quote="", page="", body=True):
        return {"Lead ID": lead_id, "Email": drafts.FIRST_EMAIL, "To": to, "Company": company,
                "Subject": "[The subject, from the handbook]" if body else "",
                "Body": demo_body(first, company) if body else "", "Opening quote": quote,
                "Quote page": page, "Status": status, "Why": why, "Approval hash": "",
                "Handbook hash": "demo-hash", "Written": '{"demo": true}' if body else "",
                "Prepared at (UTC)": "2026-09-28 12:40:00"}
    return [
        row("A-0007", "Lakeside Concrete", "jo@lakeside-concrete.test", "Jo", drafts.WAITING,
            drafts.OFFER_NOT_APPROVED, "We pour foundations and slabs for commercial buildings.",
            "https://lakeside-concrete.test/services"),
        row("A-0008", "Pioneer Paving", "ali@pioneer-paving.test", "Ali", drafts.WAITING,
            "\n".join([drafts.OFFER_NOT_APPROVED, 'the company name "Pioneer Paving" was not '
                       "found on its own site; check it"]),
            "Parking lots and access roads for commercial sites.",
            "javascript:alert(2)"),
        row("A-0013", "Granite Works", "sky@granite-works.test", "Sky", drafts.HELD,
            "no quote is good enough to open with: reads as a list of markets", body=False),
    ]


def suppression():
    return [{"Address or domain": "kim@harbor-glass.test", "Reason": "bounced: 5.1.1",
             "Added at": "2026-09-22 18:10:00", "Source": "sync: lead A-0005"},
            {"Address or domain": "lee@summit-roofing.test", "Reason": "opted out: no thanks",
             "Added at": "2026-09-23 12:20:00", "Source": "sync: lead A-0006"}]


def runs():
    return [{"Run at (UTC)": "2026-09-28 12:50:04", "Job": "sync", "Where": "cloud-run",
             "Result": "OK", "Detail": "read 3 messages; new events: none; cursor 2026-09-28T12:50:00Z"},
            {"Run at (UTC)": "2026-09-28 12:52:10", "Job": "tracking", "Where": "cloud-run",
             "Result": "OK", "Detail": "recorded 0 hits"}]


def snapshot():
    """The demo console, exactly as the server would send it."""
    data = console_model.build({row["Lead ID"]: row for row in rows()}, events(), suppression(),
                               runs(), settings=SETTINGS, now=NOW, handbook_doc_id=HANDBOOK,
                               draft_rows=draft_rows())
    data["signed_in_as"] = "admin@lakshyaa.ai"
    data["import_enabled"] = False  # the static demo has no server to import through
    data["playbook_enabled"] = False  # likewise, the playbook upload needs a server
    data["reply_enabled"] = False  # the reply-draft candidate needs a server too
    return data


def text():
    return json.dumps(snapshot(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description="The console's made-up demo data")
    parser.add_argument("--write", action="store_true", help=f"rewrite {FIXTURE}")
    args = parser.parse_args()
    if args.write:
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text(), encoding="utf-8", newline="\n")
        print(f"wrote {FIXTURE}")
    else:
        sys.stdout.write(text())


if __name__ == "__main__":
    main()
