"""Signed tracking links for this system's drafts, and the HTML that carries them.

The plain text of a draft is what the founder approves. With tracking on, the same words also go
out as HTML: the paragraphs as written, the website link routed through the tracker, and a 1x1
image at the end. A tracking link carries a signed, opaque draft ID (and, for a click, the link's
number and its destination) and nothing about the recipient.

A signature stops a forged or altered link from being counted. It cannot stop a real link from
being fetched by a mail scanner, or by anyone who holds the email.
"""

import base64
import binascii
import hashlib
import hmac
import html
import json
import os
import re
import shutil
import subprocess
from urllib.parse import urlparse

BASE = "https://t.lakshyaa.ai"
ALLOWED_HOSTS = ("lakshyaa.ai",)  # the only sites a tracked click may lead to
SECRET = "tracking-signing-key"
PROJECT = "lakshyaa-outreach"
OPEN, CLICK = "o", "c"
VERSION = 1
URL = re.compile(r"https?://[^\s<>\"']+")


class TrackingUnavailable(RuntimeError):
    """Tracking is on but the signing key cannot be read: no draft is made."""


def key():
    """The signing key: TRACKING_KEY on Cloud Run, else Secret Manager through gcloud locally."""
    value = os.environ.get("TRACKING_KEY", "").strip()
    if not value:
        exe = shutil.which("gcloud") or shutil.which("gcloud.cmd")
        if not exe:
            raise TrackingUnavailable("the tracking signing key is not available")
        done = subprocess.run([exe, "secrets", "versions", "access", "latest", f"--secret={SECRET}",
                               f"--project={PROJECT}"], capture_output=True, text=True)
        if done.returncode != 0:
            raise TrackingUnavailable("the tracking signing key could not be read")
        value = done.stdout.strip()
    try:
        raw = bytes.fromhex(value)
    except ValueError:
        raise TrackingUnavailable("the tracking signing key is not hex") from None
    if len(raw) < 32:
        raise TrackingUnavailable("the tracking signing key is too short")
    return raw


def _b64(data):
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text):
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def sign(payload, secret):
    body = _b64(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    mac = hmac.new(secret, body.encode(), hashlib.sha256).digest()[:16]
    return f"{body}.{_b64(mac)}"


def verify(token, secret):
    """The payload of a genuine token, or None for anything forged, altered or malformed."""
    try:
        body, mac = token.split(".", 1)
        expected = hmac.new(secret, body.encode(), hashlib.sha256).digest()[:16]
        if not hmac.compare_digest(expected, _unb64(mac)):
            return None
        payload = json.loads(_unb64(body))
    except (ValueError, TypeError, binascii.Error):
        return None
    if not isinstance(payload, dict) or payload.get("v") != VERSION:
        return None
    if payload.get("k") not in (OPEN, CLICK) or not re.fullmatch(r"[0-9a-f]{16,64}", str(payload.get("a", ""))):
        return None
    if payload["k"] == CLICK and (not isinstance(payload.get("l"), int)
                                  or not str(payload.get("u", "")).startswith("https://")):
        return None
    return payload


def allowed(url, hosts=ALLOWED_HOSTS):
    """True for an https link to one of `hosts` or a subdomain of one."""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    return parsed.scheme == "https" and any(host == h or host.endswith("." + h) for h in hosts)


def open_url(action, secret, base=BASE):
    return f"{base}/o/{sign({'v': VERSION, 'k': OPEN, 'a': action}, secret)}"


def click_url(action, index, destination, secret, base=BASE):
    return f"{base}/c/{sign({'v': VERSION, 'k': CLICK, 'a': action, 'l': index, 'u': destination}, secret)}"


def _line(text, action, secret, base, hosts, links):
    """One line of the approved text as HTML, its links made clickable; an allowed one tracked."""
    out, at = [], 0
    for found in URL.finditer(text):
        url = found.group(0).rstrip(".,;:!?)")
        end = found.start() + len(url)
        out.append(html.escape(text[at:found.start()]))
        target = url
        if allowed(url, hosts):
            target = click_url(action, len(links), url, secret, base)
            links.append(url)
        out.append(f'<a href="{html.escape(target, quote=True)}">{html.escape(url)}</a>')
        at = end
    out.append(html.escape(text[at:]))
    return "".join(out)


def tracked_html(body, action, secret, *, base=BASE, hosts=ALLOWED_HOSTS):
    """The approved plain text as HTML with its allowed links and a 1x1 image tracked.

    The words are exactly the approved body's: paragraphs where it has a blank line, line
    breaks where it has one. Nothing is added but the tracking itself.
    """
    links, paragraphs = [], []
    for block in body.split("\n\n"):
        lines = [_line(line, action, secret, base, hosts, links) for line in block.split("\n")]
        paragraphs.append("<p>" + "<br>\n".join(lines) + "</p>")
    image = (f'<img src="{html.escape(open_url(action, secret, base), quote=True)}" width="1" '
             f'height="1" alt="" style="display:block;width:1px;height:1px;border:0">')
    return '<div dir="ltr">\n' + "\n".join(paragraphs) + "\n" + image + "\n</div>\n"
