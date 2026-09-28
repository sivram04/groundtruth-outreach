"""The public tracker at t.lakshyaa.ai: notes an image load or a click, and nothing else.

It runs as its own service account, which may only publish to the tracking topic, and holds only
the signing key: no Gmail or Sheets sign-in, no lead data. For each genuine hit it queues the
signed token, the moment, the request method and the mail program's own name (at most 200
characters). It never records the IP address.

  GET /o/<token>  always answers the 1x1 image, so a forged or broken link never shows as a
                  broken picture; only a genuine open token is queued
  GET /c/<token>  a genuine click token whose destination is an allowed site is queued and
                  redirected there; anything else is "not found", so this is never an open
                  redirect

A failure to queue is logged and the visitor still gets the image or the page.
"""

import base64
import logging
import os
import uuid
from datetime import datetime, timezone

from flask import Flask, Response, request

from outreach import pubsub, tracking

app = Flask(__name__)
GIF = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
NO_STORE = {"Cache-Control": "no-store, no-cache, must-revalidate, private, max-age=0",
            "Pragma": "no-cache", "Expires": "0", "X-Robots-Tag": "noindex, nofollow"}
PUBLISH = pubsub.publish  # replaced in tests


def _secret():
    try:
        return tracking.key()
    except tracking.TrackingUnavailable:
        logging.exception("the tracker has no signing key")
        return None


def _hosts():
    configured = os.environ.get("TRACKING_ALLOWED_HOSTS", "")
    return tuple(h.strip().lower() for h in configured.split(",") if h.strip()) or tracking.ALLOWED_HOSTS


def _genuine(token, kind):
    secret = _secret()
    payload = tracking.verify(token, secret) if secret else None
    return payload if payload and payload["k"] == kind else None


def _queue(token, kind):
    hit = {"hit": uuid.uuid4().hex, "token": token, "kind": kind,
           "at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "method": request.method, "agent": request.headers.get("User-Agent", "")[:200]}
    try:
        PUBLISH(hit)
    except Exception:
        logging.exception("a tracking hit could not be queued")


@app.get("/o/<token>")
def opened(token):
    if _genuine(token, tracking.OPEN):
        _queue(token, tracking.OPEN)
    return Response(GIF, mimetype="image/gif", headers=NO_STORE)


@app.get("/c/<token>")
def clicked(token):
    payload = _genuine(token, tracking.CLICK)
    if not payload or not tracking.allowed(payload["u"], _hosts()):
        return Response("Not found", status=404, mimetype="text/plain", headers=NO_STORE)
    _queue(token, tracking.CLICK)
    return Response(status=302, headers={**NO_STORE, "Location": payload["u"]})


@app.get("/")
def root():
    return Response("Not found", status=404, mimetype="text/plain", headers=NO_STORE)
