-- One connected Sheet per account (not per project): the founder's own use case is one Sheet
-- per purpose, and each purpose is already its own account. `sheet_id` is blank until the
-- account's first Sheet is provisioned or linked (outreach/tenant_sheet.py).
ALTER TABLE tenant.accounts ADD COLUMN sheet_id text;
