-- Per-account lead tab layout: which Sheet tabs hold leads, and the Lead ID prefix each uses.
-- NULL means "use the system default" (outreach.sheet.LEAD_TABS: A_Contact_Now/B_Contact_Now),
-- so an account that never configures this keeps working exactly like before this column
-- existed. Stored as a JSON-encoded string, not the native jsonb type - outreach/tenancy.py
-- encodes/decodes it directly (json.dumps/json.loads), the same shape outreach.sheet.LEAD_TABS
-- already is in Python, without needing a DB-driver-specific JSON adapter.
ALTER TABLE tenant.accounts ADD COLUMN lead_tabs text;
