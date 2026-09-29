// The data GET /api/snapshot sends: outreach/console_model.py `build`, version 1.
// Anything that refers to a lead does so by its Lead ID; a date is an ISO string.

export type Status = "" | "DRAFTED" | "SENT" | "REPLIED" | "OPTED_OUT" | "BOUNCED" | "REVIEW_NEEDED";

export interface LeadEvent {
  when: string;
  event: string;
  step: string;
  address: string;
  match: string;
  detail: string;
}

export interface DraftSeen {
  kind: string;
  status: "RESERVED" | "CREATED";
  at: string;
  tracked: boolean;
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
  drafts: DraftSeen[];
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
  drafts: (DraftSeen & { lead_id: string })[];
  ready: string[] | null;
  approvals: Approvals | null;
  sync: Run | null;
  tracking_run: Run | null;
  event_count: number;
  suppression_count: number | null;
  links: { sheet: string; handbook: string; gmail_account: string };
  signed_in_as: string;
}
