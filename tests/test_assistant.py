"""The console's assistant, offline: it answers only from the Sheet, invents no figure, and can
do nothing but read. Nothing here calls Gemini."""

import json
import re
from pathlib import Path

import pytest

import console_fixture as fx
from outreach import assistant

DATA = fx.snapshot()
CONSOLE = Path(__file__).resolve().parent.parent / "console" / "src"


def answering(said, usage=None):
    def model(prompt, schema):
        model.prompt, model.schema = prompt, schema
        return said, usage or {"totalTokenCount": 900}
    model.prompt = ""
    return model


def ask(said, question="What needs me today?", data=None, limit=None):
    return assistant.ask(question, data or DATA, model=answering(said),
                         limit=limit or assistant.Limit())


def refusal(said, question="What needs me today?", data=None):
    with pytest.raises(assistant.Refused) as caught:
        ask(said, question, data)
    return caught.value


# --- what it may answer ---------------------------------------------------------------------

def test_an_answer_from_the_sheet_comes_back_with_the_leads_and_a_page_to_open():
    out = ask({"answer": "Acme Plumbing replied on Thu 2026-09-24. Answer it by hand.",
               "lead_ids": ["A-0002"],
               "link": {"page": "lead", "lead_id": "A-0002", "label": "Open Acme Plumbing"}})
    assert out["answer"].startswith("Acme Plumbing replied")
    assert out["lead_ids"] == ["A-0002"]
    assert out["link"] == {"page": "lead", "lead_id": "A-0002", "label": "Open Acme Plumbing",
                           "show": ""}
    assert out["tokens"] == 900


def test_it_is_given_the_console_s_own_figures_and_told_it_cannot_send():
    model = answering({"answer": "Nothing needs you."})
    assistant.ask("anything", DATA, model=model, limit=assistant.Limit())
    given = json.loads(model.prompt.split("FACTS\n", 1)[1].split("\nTHE FOUNDER ASKS")[0])
    assert given["drafts_by_status"] == DATA["drafts_summary"]
    assert [d["lead_id"] for d in given["drafts"]] == [d["lead_id"] for d in DATA["drafts"]]
    assert {item["lead_id"] for item in given["needs_you"]} == {i["lead_id"] for i in DATA["needs_you"]}
    assert given["nothing_here_can_send"] is True
    assert "cannot send an email" in model.prompt and "only from FACTS" not in model.prompt


def test_the_model_is_handed_these_facts_and_no_others():
    """What the model sees is fixed here on purpose: a new field reaches it only deliberately."""
    assert set(assistant.facts(DATA)) == {
        "today", "read_at", "counts_by_tier", "drafts_by_status", "needs_you",
        "follow_ups_coming_up", "drafts", "leads", "leads_left_out_of_this_list",
        "leads_never_touched", "what_drafting_waits_for", "last_mailbox_sync",
        "nothing_here_can_send"}


def test_the_facts_never_carry_the_founders_postal_address_or_phone():
    given = json.dumps(assistant.facts(DATA))
    assert fx.SETTINGS["postal_address"] not in given
    assert fx.SETTINGS["sender_phone"] not in given


def test_leads_nobody_has_touched_are_counted_not_described():
    """An active lead is described; one nobody has touched is only counted; and past the cap the
    rest are counted too, so the model is never handed the whole Sheet."""
    many = {**DATA, "leads": DATA["leads"] + [
        {**DATA["leads"][0], "id": f"B-{n:04d}", "status": "", "ready": False, "draft": None,
         "blockers": ["email check is not done"]} for n in range(200, 260)] + [
        {**DATA["leads"][0], "id": f"B-{n:04d}", "status": "SENT"} for n in range(300, 500)]}
    given = assistant.facts(many)
    untouched = sum(1 for lead in DATA["leads"] if not (lead["status"] or lead["ready"] or lead["draft"]))
    assert given["leads_never_touched"] == untouched + 60
    assert len(given["leads"]) <= assistant.MAX_LEADS
    assert all(not lead["lead_id"].startswith("B-02") for lead in given["leads"])
    assert len(given["leads"]) == assistant.MAX_LEADS
    assert given["leads_left_out_of_this_list"] > 0


# --- what it may never do -------------------------------------------------------------------

@pytest.mark.parametrize("answer", [
    "You have 47 leads waiting.",  # 47 is nowhere in the Sheet
    "That is about a 41% reply rate.",
    "They owe you 1,382 dollars.",
    "The next one goes out on 2031-04-19.",
])
def test_an_answer_holding_a_figure_the_sheet_does_not_have_is_not_shown(answer):
    stopped = refusal({"answer": answer})
    assert "have not answered" in stopped.said
    assert "not in the facts" in stopped.why


def test_a_figure_the_sheet_does_have_is_fine():
    assert ask({"answer": "3 drafts are written, and 2 wait for your approval."})["answer"]


def test_an_answer_naming_an_address_the_sheet_does_not_have_is_not_shown():
    stopped = refusal({"answer": "Write to owner@unknown-company.test about it."})
    assert "does not have" in stopped.said and "addresses not in the facts" in stopped.why
    assert ask({"answer": "Write to pat@acme-plumbing.test."})["answer"]  # this one is a lead's


def test_a_lead_or_a_page_it_made_up_is_dropped_rather_than_shown():
    out = ask({"answer": "Nothing needs you.", "lead_ids": ["A-0002", "Z-9999"],
               "link": {"page": "settings", "label": "Open settings"}})
    assert out["lead_ids"] == ["A-0002"] and out["link"] is None
    assert ask({"answer": "Nothing needs you.",
                "link": {"page": "lead", "lead_id": "Z-9999", "label": "Open it"}})["link"] is None
    assert ask({"answer": "Nothing needs you.",
                "link": {"page": "leads", "show": "everything", "label": "See them"}}
               )["link"]["show"] == ""


def test_an_empty_or_enormous_answer_is_refused():
    assert refusal({"answer": "   "}).why == "the model returned no answer"
    assert "briefly" in refusal({"answer": "word " * 300}).said


def test_a_model_that_fails_is_never_an_answer():
    def broken(prompt, schema):
        raise RuntimeError("Gemini failed")

    with pytest.raises(assistant.Refused) as caught:
        assistant.ask("anything", DATA, model=broken, limit=assistant.Limit())
    assert "could not reach the model" in caught.value.said
    assert "RuntimeError" in caught.value.why


def test_a_question_that_is_empty_or_too_long_never_reaches_the_model():
    asked = []

    def counting(prompt, schema):
        asked.append(prompt)
        return {"answer": "Nothing needs you."}, {}

    for question in ("", "  ", "x" * (assistant.MAX_QUESTION + 1)):
        with pytest.raises(assistant.Refused) as caught:
            assistant.ask(question, DATA, model=counting, limit=assistant.Limit())
        assert "could not reach the model" not in caught.value.said
    assert asked == []


def test_only_so_many_questions_an_hour_reach_the_model():
    clock = [1000.0]
    limit = assistant.Limit(most=2, clock=lambda: clock[0])
    for _ in range(2):
        ask({"answer": "Nothing needs you."}, limit=limit)
    with pytest.raises(assistant.Refused) as caught:
        ask({"answer": "Nothing needs you."}, limit=limit)
    assert "in an hour" in caught.value.said
    clock[0] += 3601
    assert ask({"answer": "Nothing needs you."}, limit=limit)["answer"]


def test_the_module_can_neither_send_nor_write():
    source = (Path(assistant.__file__)).read_text(encoding="utf-8")
    for forbidden in ("gmail", "drafts.prepare", "write_drafts", "append_events", "Store("):
        assert forbidden not in source, forbidden


# --- the pages it may point at exist --------------------------------------------------------

def test_the_links_it_may_offer_are_pages_and_filters_the_app_really_has():
    pages = set(re.findall(r'"(dashboard|drafts|leads|lead|sources|missing)"',
                           (CONSOLE / "router.ts").read_text(encoding="utf-8")))
    assert set(assistant.PAGES) <= pages
    shows = re.findall(r'\["([a-z-]+)", "', (CONSOLE / "filters.ts").read_text(encoding="utf-8"))
    assert list(assistant.SHOWS) == shows
