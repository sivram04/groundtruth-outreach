import pytest
import requests

from outreach import checks

MX = {"airclaws.com": True, "af1hvac.com": True, "deadco.com": False, "yahoo.com": True,
      "sbcglobal.net": True}
UP = (True, "")
LIVE = {"https://airclaws.com/": UP, "https://airforceone.com/": UP,
        "https://gone.com/": (False, "website returns HTTP 404: https://gone.com/")}


def lead(**kw):
    base = {"id": "A-0001", "email": "ray@airclaws.com", "website": "https://airclaws.com/",
            "warning": "", "sent_by_hand": ""}
    return {**base, **kw}


def run(l, seen=None, published=None):
    return checks.check(l, seen or {}, MX, LIVE, published or {})


# --- rules -------------------------------------------------------------------------------

def test_ok():
    assert run(lead())[0] == checks.OK


def test_sent_by_hand_wins():
    assert run(lead(sent_by_hand="Sent email on 9/22/2026")) == (checks.SENT_BY_HAND, "Sent email on 9/22/2026")


def test_bad_format_and_missing():
    assert run(lead(email="ray@airclaws"))[0] == checks.INVALID
    assert run(lead(email=""))[0] == checks.INVALID


def test_duplicate_points_to_first():
    assert run(lead(id="B-0003"), {"ray@airclaws.com": "A-0001"}) == (checks.DUPLICATE, "same address as A-0001")
    assert run(lead(), {"ray@airclaws.com": "A-0001"})[0] == checks.OK  # the first row itself


def test_no_mail_servers_is_invalid():
    assert run(lead(email="bob@deadco.com", website=""))[0] == checks.INVALID


def test_unknown_mail_servers_is_risky_not_invalid():
    r, why = run(lead(email="bob@unknown.com", website=""))
    assert r == checks.RISKY and "could not check" in why


def test_apollo_warning_is_risky_without_double_counting_domain():
    r, why = run(lead(email="freeman@af1hvac.com", website="https://airforceone.com/",
                      warning="MISMATCH: email domain af1hvac.com is not airforceone.com"))
    assert r == checks.RISKY and "Apollo warning" in why and "differs" not in why


def test_domain_mismatch_without_warning_is_risky():
    r, why = run(lead(email="freeman@af1hvac.com", website="https://airforceone.com/"))
    assert r == checks.RISKY and "differs from website" in why


def test_generic_inbox_and_404_site_are_risky():
    r, why = run(lead(email="info@airclaws.com", website="https://gone.com/"))
    assert r == checks.RISKY and "generic inbox" in why and "HTTP 404" in why


@pytest.mark.parametrize("local", ["employment", "hiring", "orders", "quotes", "marketing", "warranty",
                                   "Employment", "resumes", "purchasing"])
def test_role_inboxes_are_risky(local):
    r, why = run(lead(email=f"{local}@airclaws.com"))
    assert r == checks.RISKY and "generic inbox" in why


@pytest.mark.parametrize("local", ["ray", "luke", "trevor", "orderly.bob", "quoteman"])
def test_named_people_are_not_role_inboxes(local):
    assert run(lead(email=f"{local}@airclaws.com"))[0] == checks.OK


def test_personal_mailbox_found_on_site_is_ok():
    pub = {("john@yahoo.com", "https://airclaws.com/"): (True, "https://airclaws.com/contact")}
    r, why = run(lead(email="john@yahoo.com"), published=pub)
    assert r == checks.OK and "found on the company's website" in why


def test_personal_mailbox_not_on_site_is_risky_whatever_the_label_says():
    # A-0155: labelled "read from their website", but the site shows a different address.
    pub = {("apex.mechanical@sbcglobal.net", "https://airclaws.com/"): (False, "apex@apexmechsys.com")}
    r, why = run(lead(email="apex.mechanical@sbcglobal.net", source="read from their website"), published=pub)
    assert r == checks.RISKY and "not found on the company's website" in why and "apex@apexmechsys.com" in why


def test_personal_mailbox_unreadable_site_is_risky():
    pub = {("john@yahoo.com", "https://airclaws.com/"): (None, "could not read the website")}
    r, why = run(lead(email="john@yahoo.com"), published=pub)
    assert r == checks.RISKY and "could not be confirmed" in why


def test_subdomain_website_matches():
    assert checks.base_domain(checks.site_domain("https://www.shop.airclaws.com")) == "airclaws.com"


# --- website probe -----------------------------------------------------------------------

class Resp:
    def __init__(self, status, text=""):
        self.status_code, self.text = status, text


@pytest.fixture
def web(monkeypatch):
    pages = {}

    def fake_get(url, **kw):
        if url not in pages:
            raise requests.ConnectionError("no route")
        return pages[url]
    monkeypatch.setattr(checks.requests, "get", fake_get)
    monkeypatch.setattr(checks.time, "sleep", lambda s: None)
    return pages


@pytest.mark.parametrize("status,loads", [(200, True), (301, True), (403, True), (401, True),
                                          (429, True), (404, False), (410, False), (400, False),
                                          (500, False), (503, False)])
def test_probe_status_codes(web, status, loads):
    web["https://x.com/"] = Resp(status)
    assert checks.probe_website("https://x.com/")[0] is loads


def test_probe_404_reason_names_the_code(web):
    web["https://x.com/"] = Resp(404)
    assert "HTTP 404" in checks.probe_website("https://x.com/")[1]


def test_probe_missing_page_but_live_homepage_loads(web):
    web["https://x.com/contact"] = Resp(404)
    web["https://x.com/"] = Resp(200)
    loads, detail = checks.probe_website("https://x.com/contact")
    assert loads and "homepage loads" in detail


def test_probe_missing_page_and_dead_homepage(web):
    web["https://x.com/contact"] = Resp(404)
    web["https://x.com/"] = Resp(404)
    assert checks.probe_website("https://x.com/contact")[0] is False


def test_probe_survives_one_dropped_connection(monkeypatch):
    calls = []

    def flaky(url, **kw):
        calls.append(url)
        if len(calls) == 1:
            raise requests.exceptions.SSLError("passing handshake failure")
        return Resp(200)
    monkeypatch.setattr(checks.requests, "get", flaky)
    monkeypatch.setattr(checks.time, "sleep", lambda s: None)
    assert checks.probe_website("https://x.com/") == (True, "")


def test_probe_no_answer(web, monkeypatch):
    monkeypatch.setattr(checks.time, "sleep", lambda s: None)
    loads, detail = checks.probe_website("https://nothing.com/")
    assert loads is False and "does not answer" in detail


# --- finding a published address ---------------------------------------------------------

def test_emails_in_page_decodes_obfuscation():
    key = 0x42
    cf = f"{key:02x}" + "".join(f"{ord(c) ^ key:02x}" for c in "bob@gmail.com")
    html = (f'<a href="mailto:ann%40yahoo.com">x</a> tim [at] aol [dot] com '
            f'<span class="__cf_email__" data-cfemail="{cf}">[protected]</span>')
    assert {"ann@yahoo.com", "tim@aol.com", "bob@gmail.com"} <= checks.emails_in_page(html)


def test_emails_in_page_drops_image_names_and_placeholders():
    html = ('<img src="bryant-dealer-rgb-300x142@2x.png"> <input placeholder="your@email.com"> '
            'user@domain.com v@build.version real@company.com')
    assert checks.emails_in_page(html) == {"real@company.com"}


def test_find_published_follows_contact_link(web):
    web["https://x.com/robots.txt"] = Resp(404)
    web["https://x.com/"] = Resp(200, '<a href="/contact-us">Contact</a>')
    web["https://x.com/contact-us"] = Resp(200, "Call or write: owner@gmail.com")
    assert checks.find_published("owner@gmail.com", "https://x.com/") == (True, "https://x.com/contact-us")


def test_find_published_reports_what_the_site_shows_instead(web):
    web["https://x.com/robots.txt"] = Resp(404)
    web["https://x.com/"] = Resp(200, "apex@apexmechsys.com")
    assert checks.find_published("apex.mechanical@sbcglobal.net", "https://x.com/") == (False, "apex@apexmechsys.com")


def test_find_published_honours_robots(web):
    web["https://x.com/robots.txt"] = Resp(200, "User-agent: *\nDisallow: /")
    web["https://x.com/"] = Resp(200, "owner@gmail.com")
    found, why = checks.find_published("owner@gmail.com", "https://x.com/")
    assert found is None and "could not read" in why


def test_find_published_ignores_other_sites(web):
    web["https://x.com/robots.txt"] = Resp(404)
    web["https://x.com/"] = Resp(200, '<a href="https://elsewhere.com/contact">c</a>')
    web["https://elsewhere.com/contact"] = Resp(200, "owner@gmail.com")
    assert checks.find_published("owner@gmail.com", "https://x.com/")[0] is False
