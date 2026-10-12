"""Give a connected account its own Sheet: provision a brand-new one, or link an existing one
the account's owner already has. Dependency-injected (`api`/`conn` always passed in), matching
this repo's convention everywhere else - fully testable offline with fakes.
"""

from outreach import tenancy


class LinkRefused(Exception):
    """A proposed existing Sheet could not be linked; nothing was stored."""


def ensure_sheet(api, conn, account_id, *, link_sheet_id=None, title=None):
    """This account's Sheet id - the one it already has, or a freshly provisioned/linked one.

    `link_sheet_id`, when given, must name a Sheet the caller's own Google credential can
    actually open; this is checked with a real read before it is trusted and stored, so a
    typo'd or inaccessible id is refused rather than silently remembered. With no
    `link_sheet_id`, a brand-new blank spreadsheet is created and its id stored instead.
    Idempotent: an account that already has a Sheet keeps it - this never overwrites one
    silently, since switching Sheets out from under an account would strand data already
    written under the old one.
    """
    existing = tenancy.get_sheet_id(conn, account_id)
    if existing:
        return existing

    if link_sheet_id:
        sheet_id = str(link_sheet_id).strip()
        try:
            api.get(spreadsheetId=sheet_id).execute()
        except Exception as exc:
            raise LinkRefused(
                f"could not open the Sheet {sheet_id!r} with this account's Google connection; "
                f"check the id and that this account has access") from exc
    else:
        created = api.create(body={"properties": {"title": title or "Lakshyaa outreach leads"}}).execute()
        sheet_id = created.get("spreadsheetId")
        if not sheet_id:
            raise LinkRefused("Google did not return a usable Sheet id for the new spreadsheet")

    tenancy.set_sheet_id(conn, account_id, sheet_id)
    return sheet_id
