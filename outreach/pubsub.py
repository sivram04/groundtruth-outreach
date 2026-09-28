"""The tracking queue, over Pub/Sub's REST API, as the calling service's own identity.

The tracker may only publish to the topic; the worker may only pull from and acknowledge on the
subscription (IAM, set up in deploy/). A message is acknowledged only after the Sheet has it.
"""

import base64
import json

import requests

from outreach.google_auth import cloud_token

PROJECT = "lakshyaa-outreach"
TOPIC = "outreach-tracking-hits"
SUBSCRIPTION = "outreach-tracking-worker"
API = "https://pubsub.googleapis.com/v1"


def _post(path, body, timeout):
    response = requests.post(f"{API}/projects/{PROJECT}/{path}", json=body, timeout=timeout,
                             headers={"Authorization": f"Bearer {cloud_token()}"})
    response.raise_for_status()
    return response.json()


def publish(data, topic=TOPIC):
    encoded = base64.b64encode(json.dumps(data, separators=(",", ":")).encode()).decode()
    _post(f"topics/{topic}:publish", {"messages": [{"data": encoded}]}, timeout=10)


class Queue:
    """Pull and acknowledge on the worker's subscription."""

    def __init__(self, subscription=SUBSCRIPTION):
        self.subscription = subscription

    def pull(self, max_messages=100):
        """[(ack id, message data)] currently waiting; an unreadable message comes back as None.

        Answers at once instead of waiting for messages to arrive: an empty queue otherwise held
        each five-minute run for about 20 seconds (measured on the first scheduled runs,
        2026-09-28). A hit that arrives while this answers is simply taken by the next run."""
        found = _post(f"subscriptions/{self.subscription}:pull",
                      {"maxMessages": max_messages, "returnImmediately": True},
                      timeout=30).get("receivedMessages", [])
        out = []
        for item in found:
            try:
                data = json.loads(base64.b64decode(item["message"].get("data", "")))
            except (ValueError, TypeError):
                data = None
            out.append((item["ackId"], data))
        return out

    def ack(self, ack_ids):
        for start in range(0, len(ack_ids), 500):
            _post(f"subscriptions/{self.subscription}:acknowledge",
                  {"ackIds": ack_ids[start:start + 500]}, timeout=30)
