"""Stage 5 tracking, offline: signed links, the HTML that carries them, and the public tracker.

A forged or altered link must never be counted, the tracker must never redirect anywhere but
the allowed site, and a visitor must always get the image or the page.
"""

import html as html_lib
import re

import pytest

from outreach import tracker, tracking

KEY = bytes(range(32))
OTHER = bytes(range(1, 33))
ACTION = "a" * 32
SITE = "https://lakshyaa.ai"


# --- signed tokens ----------------------------------------------------------------------------

def token_of(url):
    return url.rsplit("/", 1)[1]


def test_a_genuine_token_says_what_it_was_signed_with():
    opened = tracking.verify(token_of(tracking.open_url(ACTION, KEY)), KEY)
    clicked = tracking.verify(token_of(tracking.click_url(ACTION, 0, SITE, KEY)), KEY)
    assert opened == {"v": 1, "k": "o", "a": ACTION}
    assert clicked == {"v": 1, "k": "c", "a": ACTION, "l": 0, "u": SITE}


@pytest.mark.parametrize("tamper", [
    lambda t: t.replace(t.split(".")[0], tracking._b64(b'{"a":"' + b"b" * 32 + b'","k":"o","v":1}')),
    lambda t: t[:-2] + ("AA" if not t.endswith("AA") else "BB"),
    lambda t: t.split(".")[0],
    lambda t: "garbage",
    lambda t: "",
])
def test_an_altered_or_malformed_token_is_refused(tamper):
    token = token_of(tracking.open_url(ACTION, KEY))
    assert tracking.verify(tamper(token), KEY) is None


def test_a_token_signed_with_another_key_is_refused():
    assert tracking.verify(token_of(tracking.open_url(ACTION, OTHER)), KEY) is None


@pytest.mark.parametrize("payload", [
    {"v": 2, "k": "o", "a": ACTION},
    {"v": 1, "k": "x", "a": ACTION},
    {"v": 1, "k": "o", "a": "not hex"},
    {"v": 1, "k": "c", "a": ACTION, "l": 0, "u": "http://lakshyaa.ai"},
    {"v": 1, "k": "c", "a": ACTION, "l": "0", "u": SITE},
])
def test_a_signed_token_of_the_wrong_shape_is_refused(payload):
    assert tracking.verify(tracking.sign(payload, KEY), KEY) is None


@pytest.mark.parametrize("url,ok", [
    ("https://lakshyaa.ai", True), ("https://www.lakshyaa.ai/about", True),
    ("http://lakshyaa.ai", False), ("https://evil.test", False),
    ("https://lakshyaa.ai.evil.test", False), ("https://notlakshyaa.ai", False),
])
def test_only_https_links_to_the_allowed_site_may_be_followed(url, ok):
    assert tracking.allowed(url) is ok


def test_without_a_key_tracking_is_unavailable(monkeypatch):
    monkeypatch.delenv("TRACKING_KEY", raising=False)
    monkeypatch.setattr(tracking.shutil, "which", lambda name: None)
    with pytest.raises(tracking.TrackingUnavailable):
        tracking.key()
    monkeypatch.setenv("TRACKING_KEY", "ab" * 8)
    with pytest.raises(tracking.TrackingUnavailable, match="too short"):
        tracking.key()
    monkeypatch.setenv("TRACKING_KEY", KEY.hex())
    assert tracking.key() == KEY


# --- the HTML copy of the approved words ------------------------------------------------------

BODY = ("Hi Sam,\n\nWould a call next week help? <Yes> & no.\n\nBest,\nA Founder\n"
        "https://lakshyaa.ai\nhttps://other.test/page.\nIf you don't want further outreach, stop.")


def test_the_html_says_exactly_the_approved_words():
    out = tracking.tracked_html(BODY, ACTION, KEY)
    text = html_lib.unescape(re.sub(r"<[^>]+>", "", out.replace("<br>\n", "\n").replace("</p>\n<p>", "\n\n")))
    assert text.strip() == BODY
    assert "&lt;Yes&gt; &amp; no." in out


def test_text_before_a_link_on_the_same_line_is_escaped_too():
    out = tracking.tracked_html("See <this> & https://lakshyaa.ai", ACTION, KEY)
    assert "See &lt;this&gt; &amp; <a href=" in out and "<this>" not in out


def test_the_website_link_is_tracked_and_other_links_are_left_alone():
    out = tracking.tracked_html(BODY, ACTION, KEY)
    hrefs = re.findall(r'href="([^"]+)"', out)
    assert len(hrefs) == 2
    tracked = tracking.verify(token_of(html_lib.unescape(hrefs[0])), KEY)
    assert tracked == {"v": 1, "k": "c", "a": ACTION, "l": 0, "u": SITE}
    assert html_lib.unescape(hrefs[1]) == "https://other.test/page"  # untracked; the full stop stays outside
    assert ">https://lakshyaa.ai</a>" in out and "</a>." in out


def test_the_html_ends_with_one_image_carrying_the_draft_id():
    out = tracking.tracked_html(BODY, ACTION, KEY)
    images = re.findall(r'<img src="([^"]+)"', out)
    assert len(images) == 1 and images[0].startswith(tracking.BASE + "/o/")
    payload = tracking.verify(token_of(html_lib.unescape(images[0])), KEY)
    assert payload == {"v": 1, "k": "o", "a": ACTION}  # nothing about the recipient


# --- the public tracker -----------------------------------------------------------------------

@pytest.fixture
def app(monkeypatch):
    monkeypatch.setenv("TRACKING_KEY", KEY.hex())
    monkeypatch.delenv("TRACKING_ALLOWED_HOSTS", raising=False)
    queued = []
    monkeypatch.setattr(tracker, "PUBLISH", queued.append)
    return tracker.app.test_client(), queued


def test_a_genuine_open_is_queued_and_the_image_is_served_uncached(app):
    client, queued = app
    token = token_of(tracking.open_url(ACTION, KEY))
    response = client.get(f"/o/{token}", headers={"User-Agent": "Mozilla/5.0 GoogleImageProxy"},
                          environ_base={"REMOTE_ADDR": "203.0.113.9"})
    assert response.status_code == 200 and response.mimetype == "image/gif"
    assert response.data == tracker.GIF and "no-store" in response.headers["Cache-Control"]
    assert len(queued) == 1 and queued[0]["kind"] == "o" and queued[0]["token"] == token
    assert queued[0]["method"] == "GET" and "GoogleImageProxy" in queued[0]["agent"]
    assert "203.0.113.9" not in str(queued[0])  # the address is never recorded


def test_a_forged_open_still_gets_the_image_and_is_not_queued(app):
    client, queued = app
    response = client.get(f"/o/{token_of(tracking.open_url(ACTION, OTHER))}")
    assert response.status_code == 200 and response.data == tracker.GIF and queued == []


def test_a_genuine_click_is_queued_and_redirected(app):
    client, queued = app
    response = client.get(f"/c/{token_of(tracking.click_url(ACTION, 0, SITE, KEY))}")
    assert response.status_code == 302 and response.headers["Location"] == SITE
    assert [q["kind"] for q in queued] == ["c"]


@pytest.mark.parametrize("url", [
    lambda: tracking.click_url(ACTION, 0, SITE, OTHER),
    lambda: tracking.click_url(ACTION, 0, "https://evil.test/", KEY),
    lambda: tracking.open_url(ACTION, KEY),
])
def test_a_click_that_is_not_genuine_or_leads_elsewhere_is_not_found(app, url):
    client, queued = app
    response = client.get(f"/c/{token_of(url())}")
    assert response.status_code == 404 and queued == [] and "Location" not in response.headers


def test_a_click_token_on_the_image_path_is_not_an_open(app):
    client, queued = app
    assert client.get(f"/o/{token_of(tracking.click_url(ACTION, 0, SITE, KEY))}").data == tracker.GIF
    assert queued == []


def test_a_head_request_is_queued_as_one(app):
    client, queued = app
    response = client.head(f"/c/{token_of(tracking.click_url(ACTION, 0, SITE, KEY))}")
    assert response.status_code == 302 and queued[0]["method"] == "HEAD"


def test_the_allowed_sites_can_be_narrowed_by_the_service(app, monkeypatch):
    client, queued = app
    monkeypatch.setenv("TRACKING_ALLOWED_HOSTS", "example.test")
    assert client.get(f"/c/{token_of(tracking.click_url(ACTION, 0, SITE, KEY))}").status_code == 404


def test_a_queue_failure_never_breaks_the_image_or_the_link(app, monkeypatch):
    client, _ = app

    def down(hit):
        raise ConnectionError("queue unreachable")
    monkeypatch.setattr(tracker, "PUBLISH", down)
    assert client.get(f"/o/{token_of(tracking.open_url(ACTION, KEY))}").status_code == 200
    assert client.get(f"/c/{token_of(tracking.click_url(ACTION, 0, SITE, KEY))}").status_code == 302


def test_without_a_key_nothing_is_counted_and_nothing_redirects(app, monkeypatch):
    client, queued = app
    monkeypatch.delenv("TRACKING_KEY")
    monkeypatch.setattr(tracking.shutil, "which", lambda name: None)
    assert client.get(f"/o/{token_of(tracking.open_url(ACTION, KEY))}").data == tracker.GIF
    assert client.get(f"/c/{token_of(tracking.click_url(ACTION, 0, SITE, KEY))}").status_code == 404
    assert queued == []


def test_the_root_is_not_found(app):
    client, _ = app
    assert client.get("/").status_code == 404
