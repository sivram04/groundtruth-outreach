"""Run the console locally with lead import switched on, over a synthetic in-memory Store.

FOR LOCAL VERIFICATION ONLY. It never touches Google: the Store is `stage4_fakes.MemoryStore` seeded
with made-up leads, sign-in is a stub that lets one fixed email in, and nothing is deployed. It exists
so the import journey (upload/paste -> preview -> confirm -> reload) can be driven through the *real*
Flask routes and the *real* built React pages, not a static demo.

    python tools/local_import_console.py            # serves on 127.0.0.1:8139 with console/dist

Requires the built pages in `console/dist` (a container build) and the test dependencies (Flask,
openpyxl). Not part of the deployed app; it is never imported by the console or the worker.
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for path in (str(ROOT), str(ROOT / "tests")):
    if path not in sys.path:
        sys.path.insert(0, path)

from outreach import console  # noqa: E402
from stage4_fakes import MemoryStore  # noqa: E402

COLUMNS = ["Lead ID", "Company", "Decision maker", "BEST EMAIL", "Website", "Phone"]
SEED = [
    {"Lead ID": "A-0001", "Company": "Example Electric", "Decision maker": "Sam Rivers",
     "BEST EMAIL": "sam@example-electric.test", "Website": "https://example-electric.test/",
     "Phone": "", "Email check": "OK", "Fit": "QUALIFIED", "Profile status": "READY"},
]


class StubVerifier:
    """Stands in for the IAP check: one fixed signed-in person, no token needed. Local only."""

    def email(self, _header):
        return "admin@lakshyaa.ai"


def main():
    store = MemoryStore(SEED, lead_columns=COLUMNS)  # one shared, in-memory Store; appends persist
    app = console.create_app(
        verifier=StubVerifier(),
        store=lambda: store,
        settings=lambda: {"sender_email": "admin@lakshyaa.ai"},
        clock=lambda: datetime.now(timezone.utc),
        static_dir=str(ROOT / "console" / "dist"),
        enable_import=True,
    )
    app.run(host="0.0.0.0", port=8139)


if __name__ == "__main__":
    main()
