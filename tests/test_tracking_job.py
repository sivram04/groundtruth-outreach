"""Stage 5, offline: queued hits become events, counted only when they should be; the pass-test
draft goes only to the founder's own inbox; the Dashboard is formulas.
"""

import uuid

import pytest

from outreach import dashboard, sequence, sync, tracking, tracking_check, tracking_job
from stage4_fakes import Call, FakeGmail, MemoryStore, at, lead, parsed

KEY = bytes(range(32))
ACTION = "a" * 32
SITE = "https://lakshyaa.ai"
SAM = "sam@example-electric.test"
SENT_AT = at("2026-09-22 13:18")


def token_of(url):
    return url.rsplit("/", 1)[1]


def hit(kind, when, *, action=ACTION, hit_id=None, method="GET", agent="", key=KEY):
    url = tracking.open_url(action, key) if kind == "o" else tracking.click_url(action, 0, SITE, key)
    hit_id = hit_id or uuid.uuid4().hex
    return (f"ack-{hit_id}", {"hit": hit_id, "token": token_of(url), "kind": kind, "method": method,
                              "at": when.strftime("%Y-%m-%dT%H:%M:%SZ"), "agent": agent})


class FakeQueue:
    def __init__(self, messages):
        self.batches = [list(messages)] if messages else []
        self.acked = []

    def pull(self, max_messages=100):
        return self.batches.pop(0) if self.batches else []

    def ack(self, ack_ids):
        self.acked += ack_ids


def drafted(tracked=True):
    return sync._event("A-0001", sequence.DRAFTED, sequence.INITIAL, at("2026-09-22 08:00"), SAM,
                       "DRAFT", "t-sys", "", "draft draft-9" + (", tracked" if tracked else ""),
                       key=f"draft:{ACTION}")


def sent():
    return sync._event("A-0001", sequence.SENT, sequence.INITIAL, SENT_AT, SAM, "DRAFT", "t-sys",
                       "m1", "")


def tracked_lead():
    return lead(**{"Draft action": ACTION, "Draft status": "CREATED", "Draft ID": "draft-9",
                   "Draft thread ID": "t-sys", "Draft tracked": "yes"})


def run(store, messages):
    queue = FakeQueue(messages)
    report = tracking_job.run(store=store, queue=queue, secret=KEY, now=at("2026-09-28 09:00"))
    return report, queue


# --- what is recorded, and what counts ------------------------------------------------------

def test_an_open_after_the_send_is_recorded_and_counted():
    store = MemoryStore([tracked_lead()], events=[drafted(), sent()], suppression=[])
    report, queue = run(store, [hit("o", at("2026-09-22 14:00"), agent="GoogleImageProxy")])
    event = store.event_rows[-1]
    assert (event["Event"], event["Lead ID"], event["Step"]) == ("OPEN", "A-0001", "INITIAL")
    assert event["Detail"] == f"draft {ACTION}, Google image proxy"
    assert store.rows["A-0001"]["Tracked sends"] == "1" and store.rows["A-0001"]["Opens (est.)"] == "1"
    assert store.rows["A-0001"]["Clicks"] == "0"
    assert len(queue.acked) == 1 and store.runs[-1]["Job"] == "tracking"
    assert report["recorded"] == {"OPEN": 1}


def test_an_open_before_the_send_is_kept_but_never_counted():
    store = MemoryStore([tracked_lead()], events=[drafted(), sent()], suppression=[])
    run(store, [hit("o", at("2026-09-22 12:30"))])  # the founder looking at the draft
    assert store.event_rows[-1]["Event"] == "OPEN"
    assert sequence.tracking_cells(store.event_rows)["Opens (est.)"] == "0"


def test_an_open_that_arrives_before_sync_records_the_send_counts_once_it_does():
    store = MemoryStore([tracked_lead()], events=[drafted()], suppression=[])
    run(store, [hit("o", at("2026-09-22 13:30"))])
    assert sequence.tracking_cells(store.event_rows)["Opens (est.)"] == ""  # no send yet
    assert sequence.tracking_cells(store.event_rows + [sent()])["Opens (est.)"] == "1"


def test_scanner_clicks_are_recorded_but_not_counted():
    store = MemoryStore([tracked_lead()], events=[drafted(), sent()], suppression=[])
    run(store, [hit("c", at("2026-09-22 13:18")),  # the second it arrived
                hit("c", at("2026-09-22 13:30")),
                hit("c", at("2026-09-22 13:45"), method="HEAD")])
    assert [e["Event"] for e in store.event_rows[2:]] == ["CLICK", "CLICK", "CLICK"]
    assert store.rows["A-0001"]["Clicks"] == "1"


def test_a_hit_delivered_twice_or_in_a_burst_is_recorded_once():
    store = MemoryStore([tracked_lead()], events=[drafted(), sent()], suppression=[])
    twice = hit("o", at("2026-09-22 14:00"), hit_id="h1")
    run(store, [twice, twice, hit("o", at("2026-09-22 14:00")), hit("o", at("2026-09-22 14:05"))])
    assert store.rows["A-0001"]["Opens (est.)"] == "2"
    runs = len(store.runs)
    report, _ = run(store, [twice])  # delivered again on a later run
    assert report["recorded"] == {} and store.rows["A-0001"]["Opens (est.)"] == "2"
    assert len(store.runs) == runs  # a run that records nothing leaves the Runs tab alone


def test_a_forged_hit_is_dropped_and_acknowledged():
    store = MemoryStore([tracked_lead()], events=[drafted(), sent()], suppression=[])
    report, queue = run(store, [hit("o", at("2026-09-22 14:00"), key=bytes(range(1, 33))),
                                ("ack-junk", None)])
    assert report["dropped"] == 2 and len(store.event_rows) == 2 and len(queue.acked) == 2


def test_a_hit_for_no_known_draft_is_kept_without_a_lead():
    store = MemoryStore([lead()], events=[], suppression=[])
    run(store, [hit("o", at("2026-09-22 14:00"), action="b" * 32)])
    assert store.event_rows[-1]["Lead ID"] == "" and "Opens (est.)" not in store.rows["A-0001"]


def test_follow_up_and_test_drafts_are_found_by_their_ids():
    row = lead(**{"Follow-up action": "c" * 32, "Follow-up step": "1", "Draft action": "f" * 32})
    events = [sync._event("A-0001", sequence.FOLLOWUP_DRAFTED, "FOLLOWUP_2", at("2026-09-25 08:00"),
                          SAM, "DRAFT", "t", "", "draft d2, tracked", key="followup:" + "d" * 32),
              sync._event("TEST", sequence.DRAFTED, "TEST", at("2026-09-25 08:00"), "me@home.test",
                          "DRAFT", "t", "", "tracking test draft, tracked", key="test:" + "e" * 32)]
    found = tracking_job.actions({"A-0001": row}, events)
    assert found["f" * 32] == ("A-0001", "INITIAL")  # before sync has recorded the draft
    assert found["c" * 32] == ("A-0001", "FOLLOWUP_1")
    assert found["d" * 32] == ("A-0001", "FOLLOWUP_2")
    assert found["e" * 32] == ("TEST", "TEST")


def test_nothing_is_acknowledged_when_the_sheet_write_fails():
    store = MemoryStore([tracked_lead()], events=[drafted(), sent()], suppression=[])

    def broken(events):
        raise ConnectionError("Sheets unavailable")
    store.append_events = broken
    queue = FakeQueue([hit("o", at("2026-09-22 14:00"))])
    with pytest.raises(ConnectionError):
        tracking_job.run(store=store, queue=queue, secret=KEY, now=at("2026-09-28 09:00"))
    assert queue.acked == []


def test_an_empty_queue_touches_nothing():
    class Untouchable:
        def __getattr__(self, name):
            raise AssertionError("the Sheet was read with nothing to record")
    report = tracking_job.run(store=Untouchable(), queue=FakeQueue([]), secret=KEY)
    assert report["pulled"] == 0


def test_a_lead_never_tracked_stays_blank_never_zero():
    hand = sync._event("A-0001", sequence.SENT, sequence.INITIAL, SENT_AT, SAM, "ADDRESS", "t1", "m1", "")
    untracked = [drafted(tracked=False), hand]
    assert sequence.tracking_cells(untracked) == {"Tracked sends": "", "Opens (est.)": "", "Clicks": ""}


def test_only_the_tracked_emails_of_a_sequence_are_counted():
    fu_drafted = sync._event("A-0001", sequence.FOLLOWUP_DRAFTED, "FOLLOWUP_1", at("2026-09-25 08:00"),
                             SAM, "DRAFT", "t-sys", "", "draft d1, tracked", key="followup:" + "c" * 32)
    fu_sent = sync._event("A-0001", sequence.SENT, "FOLLOWUP_1", at("2026-09-25 09:00"), SAM, "DRAFT",
                          "t-sys", "m2", "")
    initial_open = tracking_job.hit_event(hit("o", at("2026-09-23 09:00"))[1],
                                          {"k": "o", "a": ACTION}, "A-0001", "INITIAL")
    fu_open = tracking_job.hit_event(hit("o", at("2026-09-25 10:00"), action="c" * 32)[1],
                                     {"k": "o", "a": "c" * 32}, "A-0001", "FOLLOWUP_1")
    cells = sequence.tracking_cells([drafted(tracked=False), sent(), fu_drafted, fu_sent,
                                     initial_open, fu_open])
    assert cells == {"Tracked sends": "1", "Opens (est.)": "1", "Clicks": "0"}


def test_the_queue_answers_at_once_and_acknowledges_in_batches(monkeypatch):
    from outreach import pubsub
    calls = []

    class Answer:
        def raise_for_status(self):
            pass

        def json(self):
            return {"receivedMessages": [{"ackId": "a1", "message": {"data": "eyJoaXQiOiAiaDEifQ=="}},
                                         {"ackId": "a2", "message": {"data": "!!"}}]}
    class Session:
        def post(self, url, json, timeout, headers):
            calls.append((url, json))
            return Answer()
    monkeypatch.setattr(pubsub, "cloud_token", lambda: "token")
    monkeypatch.setattr(pubsub, "_SESSION", Session())
    pulled = pubsub.Queue().pull(100)
    assert calls[0][1] == {"maxMessages": 100, "returnImmediately": True}
    assert pulled == [("a1", {"hit": "h1"}), ("a2", None)]
    pubsub.Queue().ack([f"id{n}" for n in range(1200)])
    assert [len(body["ackIds"]) for _, body in calls[1:]] == [500, 500, 200]


# --- the pass-test draft ----------------------------------------------------------------------

SETTINGS = {"sender_email": "admin@lakshyaa.ai", "sender_website": SITE}


@pytest.fixture
def drafts_on(monkeypatch):
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")


def check(to, store=None, gmail=None, settings=None):
    return tracking_check.create(to, store=store or MemoryStore([lead()], suppression=[]),
                                 gmail=gmail or FakeGmail(), settings=settings or SETTINGS,
                                 secret=KEY, now=at("2026-09-28 09:00"))


def test_the_test_draft_is_tracked_and_its_hits_come_back_as_test(drafts_on):
    store, gmail = MemoryStore([lead()], suppression=[]), FakeGmail()
    made = check("me@home.test", store, gmail)
    email = parsed(gmail.created[0])
    assert email["To"] == "me@home.test" and email["Subject"] == tracking_check.SUBJECT
    assert SITE in email.get_body(preferencelist=("plain",)).get_content()
    html = email.get_body(preferencelist=("html",)).get_content()
    assert tracking.BASE + "/o/" in html and tracking.BASE + "/c/" in html
    assert store.event_rows[-1]["Event key"] == f"test:{made['action']}"
    run(store, [hit("o", at("2026-09-28 09:05"), action=made["action"])])
    assert store.event_rows[-1]["Lead ID"] == "TEST" and store.event_rows[-1]["Event"] == "OPEN"


@pytest.mark.parametrize("to,why", [
    (SAM, "is a lead"), ("anyone@example-electric.test", "is a lead"),
    ("admin@lakshyaa.ai", "another inbox"), ("not an address", "not an email address"),
])
def test_the_test_draft_never_goes_to_a_lead_or_the_sender(drafts_on, to, why):
    with pytest.raises(tracking_check.CheckBlocked, match=why):
        check(to)


def test_the_test_draft_respects_suppression_and_the_drafting_switch(monkeypatch):
    listed = MemoryStore([lead()], suppression=[{"Address or domain": "me@home.test"}])
    monkeypatch.setenv("ENABLE_GMAIL_DRAFTS", "true")
    with pytest.raises(tracking_check.CheckBlocked, match="Suppression"):
        check("me@home.test", listed)
    with pytest.raises(tracking_check.CheckBlocked, match="Suppression"):
        check("me@home.test", MemoryStore([lead()], suppression=None))
    with pytest.raises(tracking_check.CheckBlocked, match="mailbox"):
        check("me@home.test", gmail=FakeGmail(address="other@lakshyaa.ai"))
    monkeypatch.delenv("ENABLE_GMAIL_DRAFTS")
    with pytest.raises(tracking_check.CheckBlocked, match="disabled"):
        check("me@home.test")


# --- the Dashboard ----------------------------------------------------------------------------

def test_the_dashboard_is_formulas_whose_rates_use_the_right_rows():
    table = dashboard.rows()
    assert table[0] == [dashboard.TITLE] and table[1][0] == "Metric" and len(table[1]) == 4
    labels = [row[0] for row in table]
    assert labels.index("Reply rate") == 5 and table[5][1] == '=IFERROR(TEXT(B5/B3,"0%"),"-")'
    assert table[12][3] == '=IFERROR(TEXT(D12/D10,"0%"),"-")'  # open rate over tracked leads
    for row in table[2:15]:
        assert all(cell.startswith("=") for cell in row[1:]), row[0]
    assert table[2][3] == "=B3+C3" and "A_Contact_Now" in table[2][1] and "B_Contact_Now" in table[2][2]
    assert '"A-*"' in table[3][1] and "'Events'" in table[3][1]
    # Every figure read from a lead column first checks the column exists: a missing one is 0.
    for number in (2, 4, 6, 7, 8, 9, 11, 13):
        for cell in table[number][1:3]:
            assert "ISNUMBER(MATCH(" in cell and cell.count("COUNTIF") + cell.count("SUMPRODUCT") >= 1, table[number][0]


class FakeSheets:
    """The spreadsheet calls the Dashboard makes: tab list, add a tab, read and write cells."""

    def __init__(self, tabs=(), first=""):
        self.tabs, self.first, self.written, self.added = list(tabs), first, [], []

    def get(self, spreadsheetId):
        return Call(lambda: {"sheets": [{"properties": {"title": t, "sheetId": i}}
                                        for i, t in enumerate(self.tabs)]})

    def batchUpdate(self, spreadsheetId, body):
        title = body["requests"][0]["addSheet"]["properties"]["title"]
        return Call(lambda: self.added.append(title) or self.tabs.append(title) or {})

    def values(self):
        return FakeCells(self)


class FakeCells:
    def __init__(self, sheets):
        self.sheets = sheets

    def get(self, spreadsheetId, range):
        return Call(lambda: {"values": [[self.sheets.first]]} if range.endswith("!A1")
                    else {"values": [["shown"]]})

    def update(self, spreadsheetId, range, valueInputOption, body):
        return Call(lambda: self.sheets.written.append((range, valueInputOption, body["values"])) or {})


def test_the_dashboard_tab_is_made_as_formulas():
    api = FakeSheets(["A_Contact_Now"])
    dashboard.write(api)
    assert api.added == ["Dashboard"]
    assert api.written == [("'Dashboard'!A1", "USER_ENTERED", dashboard.rows())]


def test_the_dashboard_never_writes_over_a_tab_of_the_same_name():
    taken = FakeSheets(["Dashboard"], first="My own numbers")
    with pytest.raises(RuntimeError, match="not this dashboard"):
        dashboard.write(taken)
    assert taken.written == []
    ours = FakeSheets(["Dashboard"], first=dashboard.TITLE)
    dashboard.write(ours)
    assert ours.added == [] and len(ours.written) == 1
