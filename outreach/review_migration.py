"""A read-only dry run for the Reviews-tab migration.

It reports what a migration WOULD do and never changes anything: it does not create the tab, does
not write a row, and never touches lead data. Run it against a staging Sheet first, then the real
one, before anyone applies the migration. The migration itself (creating the append-only `Reviews`
tab and its header) is a separate, approved step - this only inspects and proposes.

    python -m outreach.review_migration            # inspect the configured Sheet, print the plan
"""

import json

from outreach import review


def dry_run(api=None, spreadsheet_id=None):
    """Inspect the Sheet and report the migration plan without writing anything."""
    from outreach import sheet
    api = api or sheet._api()
    sid = spreadsheet_id or sheet.SHEET_ID
    report = {"tab": review.REVIEWS_TAB, "expected_header": list(review.REVIEWS_HEADER),
              "would_write": False, "spreadsheet_id": sid}

    titles = {s["properties"]["title"] for s in api.get(spreadsheetId=sid).execute()["sheets"]}
    if review.REVIEWS_TAB not in titles:
        report.update(
            status="ABSENT", existing_rows=0,
            plan=[f"create an append-only tab {review.REVIEWS_TAB!r} with header "
                  f"{review.REVIEWS_HEADER}"],
            existing_data="none; the tab does not exist yet",
            rollback="delete the empty Reviews tab; no lead data is touched",
            older_revisions="revisions before the migration do not read this tab, so they are "
                            "unaffected; the store is fail-closed until the tab and header exist")
        return report

    values = api.values().get(spreadsheetId=sid,
                              range=f"'{review.REVIEWS_TAB}'").execute().get("values", [])
    header = values[0] if values else []
    data_rows = [r for r in values[1:] if any(str(c).strip() for c in r)]
    # The header must be EXACTLY the schema (no extra columns): the store enforces the same.
    if list(header) != list(review.REVIEWS_HEADER):
        report.update(
            status="HEADER_MISMATCH", found_header=list(header), existing_rows=len(data_rows),
            plan=[f"the {review.REVIEWS_TAB} tab exists with a header that is not exactly the schema; "
                  f"a person must reconcile it by hand to {review.REVIEWS_HEADER} (for example, an "
                  f"older tab without the 'Attempt ID' column needs that column inserted at position "
                  f"2 and every existing row given a unique Attempt ID). This dry run changes nothing."],
            existing_data=f"{len(data_rows)} row(s) present under a non-matching header; not read",
            rollback="none needed (nothing changes)",
            older_revisions="a header that is not exactly the schema already blocks the store "
                            "(fail-closed)")
        return report

    report.update(
        status="READY", existing_rows=len(data_rows),
        plan=["the tab and header already match; no change is needed"],
        existing_data=f"{len(data_rows)} existing review row(s), preserved (append-only; never "
                      f"rewritten)",
        rollback="none needed",
        older_revisions="older revisions ignore the tab; the store only appends and reads the "
                        "latest row")
    return report


def main():
    print(json.dumps(dry_run(), indent=2))


if __name__ == "__main__":
    main()
