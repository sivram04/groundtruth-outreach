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
GMAIL_KIND = "gmail"
SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
GMAIL_COMPOSE_SCOPE = "https://www.googleapis.com/auth/gmail.compose"


class NotConnected(Exception):
    """This account has no (usable) Google connection of the kind an API call needs."""


def _client(connector, conn, account_id, *, kind, scope, service, version):
    if scope not in SCOPES[kind]:
        raise AssertionError(f"the {kind} connection kind no longer grants the scope this needs")
    connection_id = tenancy.latest_connection_id(conn, account_id, kind)
    if connection_id is None:
        raise NotConnected(f"account {account_id} has no {kind} connection; it must connect first")
    access_token = connector.access_token(conn, account_id, connection_id, kind, scope)
    credentials = Credentials(token=access_token)
    return build(service, version, credentials=credentials, cache_discovery=False)


def sheets_api(connector, conn, account_id):
    """This account's own Sheets `spreadsheets()` client, authorized with ITS connected Google
    credential - never the founder's. Raises `NotConnected` if the account never connected (or
    its connection was revoked), `google_connect.Refused` if Google itself refuses to refresh it
    (expired/revoked token - the caller should ask the account to reconnect)."""
    return _client(connector, conn, account_id, kind=DRIVE_KIND, scope=SHEETS_SCOPE,
                  service="sheets", version="v4").spreadsheets()


def gmail_api(connector, conn, account_id):
    """This account's own Gmail client, authorized with ITS connected Google credential - never
    the founder's. Same failure modes as `sheets_api`: `NotConnected` with no connection yet,
    `google_connect.Refused` if Google refuses to refresh an expired/revoked token."""
    return _client(connector, conn, account_id, kind=GMAIL_KIND, scope=GMAIL_COMPOSE_SCOPE,
                  service="gmail", version="v1")
