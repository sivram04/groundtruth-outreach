"""Build a real Sheets API client for a connected account's own Google credential, instead of
the single-tenant `founder_credentials()` singleton every account used to share.

Dependency-injected, like every other module here: a `Connector` (already built, already does
the actual OAuth refresh and revokes a dead connection on `invalid_grant`) and a `conn` are
always passed in, never constructed internally - so this is testable with a fake connector.
"""

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from outreach import tenancy
from outreach.google_connect import SCOPES, Refused

DRIVE_KIND = "drive"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"


class NotConnected(Exception):
    """This account has no (usable) Google connection of the kind an API call needs."""


def sheets_api(connector, conn, account_id):
    """This account's own Sheets `spreadsheets()` client, authorized with ITS connected Google
    credential - never the founder's. Raises `NotConnected` if the account never connected (or
    its connection was revoked), `google_connect.Refused` if Google itself refuses to refresh it
    (expired/revoked token - the caller should ask the account to reconnect)."""
    connection_id = tenancy.latest_connection_id(conn, account_id, DRIVE_KIND)
    if connection_id is None:
        raise NotConnected(
            f"account {account_id} has no {DRIVE_KIND} connection; it must connect Google Sheets first")
    if SHEETS_SCOPE not in SCOPES[DRIVE_KIND]:
        raise AssertionError("the drive connection kind no longer grants Sheets write access")
    access_token = connector.access_token(conn, account_id, connection_id, DRIVE_KIND, SHEETS_SCOPE)
    credentials = Credentials(token=access_token)
    return build("sheets", "v4", credentials=credentials, cache_discovery=False).spreadsheets()
