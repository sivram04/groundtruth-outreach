"""The lead-management chat interpreter: deterministic, read-only, propose-then-confirm.

It restates what the founder typed as a structured proposal; it never writes and never guesses. A new
lead carries its fields verbatim; an existing lead's founder columns are protected (reported, not changed);
only system columns can be updated.
"""

from outreach import lead_chat

COLUMNS = ["Company", "Decision maker", "BEST EMAIL", "Website", "Phone", "Lead ID",
           "Email check", "Fit", "Profile status", "Profiled at", "Offerings evidence"]
LEADS = {"A-0001": {"Company": "Existing Electric", "BEST EMAIL": "old@existing.test"}}


def interp(note):
    return lead_chat.interpret(note, LEADS, columns=COLUMNS)


def test_add_proposes_a_new_lead_from_labelled_fields():
    r = interp("add | Company: Acme Electric | email: sam@acme.test | website: https://acme.test")
    assert r["status"] == "ready" and r["op"] == "add"
    assert r["fields"]["Company"] == "Acme Electric"
    assert r["fields"]["BEST EMAIL"] == "sam@acme.test"
    assert r["fields"]["Website"] == "https://acme.test"
    assert r["submission_id"].startswith("leadchat-")


def test_add_needs_a_company_and_a_way_to_reach_them():
    assert interp("add | Company: Acme Electric")["status"] == "need_more"
    assert interp("add | email: sam@acme.test")["status"] == "need_more"  # no company


def test_a_bad_email_is_rejected_not_stored():
    r = interp("add | Company: Acme | email: not-an-email")
    assert r["status"] == "bad_email" and r["value"] == "not-an-email"


def test_update_sets_system_columns_on_an_existing_lead():
    r = interp("update A-0001 | fit: qualified | profile: ready | email check: ok")
    assert r["status"] == "ready" and r["op"] == "update" and r["lead_id"] == "A-0001"
    assert r["fields"] == {"Fit": "QUALIFIED", "Profile status": "READY", "Email check": "OK"}
    assert r["company"] == "Existing Electric"


def test_updating_a_founder_column_is_reported_as_protected():
    r = interp("update A-0001 | email: new@existing.test")
    assert r["status"] == "protected" and r["lead_id"] == "A-0001"
    assert "BEST EMAIL" in r["columns"]


def test_an_update_to_an_unknown_lead_is_refused():
    assert interp("update A-9999 | fit: QUALIFIED")["status"] == "no_lead"


def test_an_instruction_with_no_readable_field_is_unclear():
    assert interp("hey what's up")["status"] == "unclear"


def test_a_bare_email_and_url_are_detected_for_an_add():
    r = interp("add | Company: Globe Plumbing | dana@globe.test | https://globe.test")
    assert r["status"] == "ready" and r["op"] == "add"
    assert r["fields"]["BEST EMAIL"] == "dana@globe.test" and r["fields"]["Website"] == "https://globe.test"


def test_a_url_inside_offerings_evidence_is_not_mangled_by_the_website_field():
    # The evidence URL must survive intact for quote matching even when a website is also given.
    r = interp('add | Company: Acme | email: a@b.test | website: https://acme.test/ '
               '| offerings evidence: "We wire commercial buildings for contractors." (https://acme.test/services)')
    assert r["status"] == "ready" and r["op"] == "add"
    assert r["fields"]["Website"] == "https://acme.test/"
    assert r["fields"]["Offerings evidence"] == '"We wire commercial buildings for contractors." (https://acme.test/services)'


def test_an_add_cannot_propose_a_field_the_tab_cannot_store():
    r = lead_chat.interpret("add | Company: Acme | email: a@b.test | fit: QUALIFIED",
                            LEADS, columns=["Company", "BEST EMAIL", "Lead ID"])  # no Fit column
    assert r["status"] == "need_more" and r["reason"] == "unstorable" and "Fit" in r["columns"]
