// The data GET /api/snapshot sends: outreach/console_model.py `build`, version 2.
// Anything that refers to a lead does so by its Lead ID; a date is an ISO string.

export type Status = "" | "DRAFTED" | "SENT" | "REPLIED" | "OPTED_OUT" | "BOUNCED" | "REVIEW_NEEDED";
export type DraftStatus = "READY" | "WAITING" | "HELD";

export interface LeadEvent {
  when: string;
  event: string;
  step: string;
  address: string;
  match: string;
  detail: string;
}

/** A draft this system made in Gmail, as the lead row records it (the older way). */
export interface GmailDraft {
  kind: string;
  status: "RESERVED" | "CREATED";
  at: string;
  tracked: boolean;
}

/** One row of the Drafts tab: a lead's first email, written and checked. */
export interface Draft {
  lead_id: string;
  kind: string;
  to: string;
  company: string;
  contact: string;
  tier: string;
  subject: string;
  body: string;
  quote: string;
  quote_page: string;
  quote_href: string;
  status: DraftStatus | string;
  status_label: string;
  why: string[];
  prepared_at: string;
}

export interface Lead {
  id: string;
  tier: string;
  tier_label: string;
  company: string;
  contact: string;
  email: string;
  website: string;
  website_href: string;
  email_check: string;
  email_reason: string;
  fit: string;
  fit_reason: string;
  profile: string;
  hold: string;
  sent_by_hand: string;
  status: Status;
  status_label: string;
  action: string;
  cells: Record<string, string>;
  origin: "SYSTEM" | "HAND" | null;
  next_followup: { step: number; date: string; day: string } | null;
  suppressed: boolean | null;
  gmail_drafts: GmailDraft[];
  draft: DraftStatus | string | null;
  ready: boolean;
  blockers: string[];
  error: string | null;
  events: LeadEvent[];
  columns: [string, string][];
}

export interface Need {
  order: number;
  label: string;
  lead_id: string;
  text: string;
  address: string;
}

export interface ComingUp {
  lead_id: string;
  step: number;
  date: string;
  day: string;
  text: string;
}

export interface TierCounts {
  prefix: string;
  label: string;
  leads: number;
  checked_ok: number;
  qualified: number;
  profiled: number;
  drafted: number;
  ready: number;
  emailed: number;
  emails_sent: number;
  replied: number;
  reply_rate: string;
  opted_out: number;
  bounced: number;
  review_needed: number;
  tracked: number;
  coverage: string;
  opened: number;
  open_rate: string;
  clicked: number;
  click_rate: string;
}

export interface Approvals {
  offer: boolean;
  followups: boolean;
  tracking: boolean;
  daily_cap: number | null;
  sender: string;
}

export interface Run {
  at: string;
  result: string;
  detail: string;
}

export interface Snapshot {
  version: number;
  read_at: string;
  today: string;
  today_text: string;
  warnings: string[];
  leads: Lead[];
  needs_you: Need[];
  coming_up: ComingUp[];
  coming_up_days: number;
  tiers: TierCounts[];
  notes: string[];
  drafts: Draft[];
  drafts_summary: { ready: number; waiting: number; held: number; waiting_for_offer: number };
  gmail_drafts: (GmailDraft & { lead_id: string })[];
  ready: string[] | null;
  approvals: Approvals | null;
  sync: Run | null;
  tracking_run: Run | null;
  event_count: number;
  suppression_count: number | null;
  links: { sheet: string; handbook: string; gmail_account: string };
  signed_in_as: string;
  /** The name of the script the server's own pages use; see api.ts runningBuild. */
  build?: string;
}
