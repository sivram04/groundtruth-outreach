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
  prepared_ago: string;
}

/** A lead's current call task (outreach/calls.py), or null when there is none. */
export interface CallTask {
  /** The scheduling outcome's Event ID: the identity a task action must name, so a stale action can
   *  never close a newer task. */
  id: string;
  status: string;
  outcome: string;
  why: string;
  note: string;
  due: string;
  due_kind: string;
  due_text: string;
  overdue: boolean;
  snoozed: boolean;
  called_at: string;
}

export interface CallHistoryItem {
  when: string;
  what: string;
  note: string;
}

/** POST /api/calls/<lead>/outcome or /task: the lead's resulting call state. */
export interface CallResult {
  recorded: boolean;
  task: CallTask | null;
  history: CallHistoryItem[];
  effect: string;
  /** null when no stop applied; true/false whether the redundant Suppression entry was written. */
  suppression_written?: boolean | null;
  /** present only on a partial success (e.g. the stop was recorded but its suppression entry was not). */
  warning?: string;
}

/** A post-call email candidate for the founder to inspect, edit or discard (outreach/post_call.py).
 *  It is never sent, never a Gmail draft, never persisted. */
export interface CallCandidate {
  outcome: string;
  to: string;
  subject: string;
  body: string;
  evidence: { quote: string; url: string } | null;
  note: string;
  callback_at: string;
  callback_text: string;
  handbook_hash: string;
  handbook_name: string;
}

/** GET /api/calls/<lead>/candidate: the candidate, or null with a reason (and `unavailable` when the
 *  call log, suppression list or handbook could not be read, as opposed to simply not applicable). */
export interface CallCandidateResult {
  candidate: CallCandidate | null;
  reason?: string;
  unavailable?: boolean;
}

/** A review of an uploaded playbook's text (outreach/playbook.py). */
export interface PlaybookReview {
  content_hash: string;
  length: number;
  initial_email: { present: boolean; paragraphs: string[]; problem?: string };
  follow_ups: Record<string, { present: boolean; paragraphs: string[] }>;
  timing: { stated: boolean; business_days: number[]; note: string };
  offer_values: Record<string, string>;
  missing: string[];
  ambiguous: string[];
  usable_for_followups: boolean;
}

/** POST /api/playbook/review: the extracted text and its review. */
export interface PlaybookUpload {
  kind: string;
  text: string;
  review: PlaybookReview;
}

/** POST /api/playbook/preview: a candidate follow-up rendered from the selected version. */
export interface PlaybookPreview {
  step: number;
  content_hash: string;
  body: string | null;
  problems: string[];
}

/** One lead in a chat call-log proposal (outreach/call_log_chat.py). */
export interface CallProposalLead {
  lead_id: string;
  company: string;
  contact: string;
  email: string;
  phone: string;
}

/** POST /api/calls/interpret: a proposal for the founder to confirm before anything is written. */
export interface CallProposal {
  status: "unclear_outcome" | "no_lead" | "choose_lead" | "need_time" | "ready";
  outcome?: string;
  note?: string;
  lead?: CallProposalLead;
  leads?: CallProposalLead[];
  due?: string;
  due_text?: string;
  /** The call time the preview was computed from; the confirm posts it so the saved due matches. */
  called_at?: string;
  callback_at?: string;
  effect?: string;
  do_not_contact?: boolean;
  submission_id?: string;
}

export interface Lead {
  id: string;
  tier: string;
  tier_label: string;
  company: string;
  contact: string;
  email: string;
  phone: string;
  call_task?: CallTask | null;
  call_history?: CallHistoryItem[];
  call_effect?: string;
  call_effect_said?: string;
  /** EMAIL, CALL or COMPANY_ONLY: how this lead can be reached (outreach/channels.py). */
  channel: string;
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
  sent_ago: string;
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
  /** Whether the lead-import flow is switched on for this server (off by default and in deploy). */
  import_enabled?: boolean;
  /** Whether the playbook upload/review/preview flow is switched on (off by default and in deploy). */
  playbook_enabled?: boolean;
  /** Whether the call-task flow is switched on for this server (off by default and in deploy). */
  calls_enabled?: boolean;
  /** Open call tasks, overdue first then by due date. `when` is the queue bucket. */
  call_tasks?: CallQueueItem[];
  calls_overdue?: number;
  calls_due_today?: number;
  /** The Call log could not be read: the queue must show an unavailable state, never "no calls due". */
  calls_unreadable?: boolean;
  /** The Suppression list could not be read: who opted out is unknown, so the queue is unavailable too. */
  suppression_unreadable?: boolean;
}

/** One open call task on the dashboard queue (outreach/console_model.build). */
export interface CallQueueItem {
  /** The scheduling outcome's Event ID: the identity each action must name. */
  id: string;
  lead_id: string;
  company: string;
  contact: string;
  phone: string;
  why: string;
  note: string;
  due: string;
  due_kind: string;
  due_text: string;
  overdue: boolean;
  when: "OVERDUE" | "TODAY" | "UPCOMING";
}

/** One accepted lead in an import preview: mapped to the destination's columns, with its channel and
 *  any fields that have no column to be stored in. */
export interface ImportAccepted {
  lead_id: string;
  channel: string;
  row: Record<string, string>;
  /** Fields with a value but no column at the destination — shown, not stored. */
  unstorable: { field: string; value: string }[];
  /** Contact values supplied but not usable (e.g. a malformed email) — shown with why, never stored. */
  invalid: { field: string; value: string; reason: string }[];
}

/** POST /api/import/preview: what would be stored, before anything is written. */
export interface ImportPreview {
  prefix: string;
  destination_columns: string[];
  accepted: ImportAccepted[];
  duplicates: { record: Record<string, string>; matched: string; reason: string }[];
  skipped: { record: Record<string, string>; reason: string; invalid?: { field: string; value: string; reason: string }[] }[];
  unstorable_fields: string[];
  summary: {
    accepted: number;
    duplicates: number;
    skipped: number;
    unstorable: number;
    invalid: number;
    by_channel: Record<string, number>;
  };
  fingerprint: string;
}

/** POST /api/import/commit: what happened. `outcome` is the ground truth:
 *  - "done": the writable leads were written (or already present);
 *  - "pending": an earlier attempt of THIS import owns some leads and has not finished - resume to
 *    complete it (never a completed import);
 *  - "blocked": some leads are owned by a DIFFERENT submission (claimed_elsewhere) - not imported here;
 *  - "uncertain": a write could not be confirmed - it may or may not have saved; reload to check. */
export interface ImportResult {
  outcome?: "done" | "pending" | "blocked" | "uncertain";
  written: number | null;
  already_present: number;
  lead_ids: string[];
  /** Leads a different submission claimed and is writing (so this commit did not). */
  claimed_elsewhere?: number;
  /** Leads an earlier attempt of this same import owns and has not finished. */
  pending?: number;
  /** True when an uncertain append was reconciled to "the rows had in fact landed". */
  reconciled?: boolean;
  message?: string;
}
