import type {
  CallCandidateResult,
  CallProposal,
  CallResult,
  ExperimentAssignResult,
  ExperimentDefineResult,
  ImportPreview,
  ImportResult,
  PlaybookPreview,
  PlaybookSelection,
  PlaybookUpload,
  ReplyCandidateResult,
  Snapshot,
} from "./types";

export const EXPECTED_VERSION = 2;

/** Why the data could not be shown, in words for the founder. `signIn` means reloading the
 *  page will take them through Google's sign-in again. */
export class LoadError extends Error {
  readonly signIn: boolean;

  constructor(message: string, signIn = false) {
    super(message);
    this.signIn = signIn;
  }
}

const SIGN_IN_ENDED = "Your sign-in has ended. Reload the page to sign in again.";

export async function loadSnapshot(fetcher: typeof fetch = fetch): Promise<Snapshot> {
  if (import.meta.env.VITE_DEMO === "1") {
    // The demo build: made-up leads, no server. Removed from the real build.
    const demo = await import("./demo/snapshot.json");
    return demo.default as unknown as Snapshot;
  }
  let response: Response;
  try {
    response = await fetcher("/api/snapshot", {
      // IAP answers a request marked like this with 401 instead of a sign-in page.
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new LoadError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  if (!isJson) {
    // Google's sign-in page, not our data: the sign-in has ended.
    throw new LoadError(SIGN_IN_ENDED, true);
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) {
    const said = typeof body === "object" && body !== null && "error" in body ? String(body.error) : "";
    throw new LoadError(said || `The console answered ${response.status}. Try again in a minute.`);
  }
  const data = body as Snapshot;
  if (!data || data.version !== EXPECTED_VERSION) {
    throw new LoadError("This page is older than the console behind it. Reload the page.", true);
  }
  return data;
}

export interface Answer {
  answer: string;
  refused: boolean;
  lead_ids?: string[];
  link?: { page: string; lead_id: string; show: string; label: string } | null;
}

/** Put one question to the assistant. It reads; it can change nothing. */
export async function askAssistant(question: string, fetcher: typeof fetch = fetch): Promise<Answer> {
  if (import.meta.env.VITE_DEMO === "1") {
    const demo = await import("./demo/answers");
    return demo.demoAnswer(question);
  }
  let response: Response;
  try {
    response = await fetcher("/api/ask", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json",
                 "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: JSON.stringify({ question }),
    });
  } catch {
    throw new LoadError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!body || typeof body !== "object" || !("answer" in body)) {
    throw new LoadError(isJson ? "The assistant could not answer just now." : SIGN_IN_ENDED, !isJson);
  }
  return body as Answer;
}

// --- the human evidence-review flow --------------------------------------------------------

export interface ReviewClaim {
  kind: string;
  text: string;
  quote_id: string;
}

export interface ReviewEvidence {
  category: string;
  quote: string;
  url: string;
  quote_id: string;
}

/** GET/POST /api/review/<lead>: outreach/review.py review_view. */
export interface ReviewView {
  lead_id: string;
  to: string;
  subject: string;
  body: string;
  claims: ReviewClaim[];
  evidence: ReviewEvidence | null;
  handbook_hash: string;
  handbook_version: string;
  fingerprint: string;
  /** The current review status resolved from the signed chain (outreach/review.resolved_status).
   *  `state` is the ground truth for whether review is permitted: "resolved" (a verified tip;
   *  `decision`/`current` are meaningful) or "REVIEW_MISSING" (no record yet) PERMIT review; any
   *  other value ("unreadable", "unverifiable", "REVIEW_CONFLICT", "REVIEW_TAMPERED") is a failed or
   *  invalid history and BLOCKS it. HTTP 200 alone does not establish a usable decision.
   *  Missing or unknown states at runtime also block; the demo uses this same contract. */
  review: {
    decision: string | null;
    reviewer?: string;
    reviewed_at?: string;
    current: boolean;
    state: string;
  };
  note: string;
}

/** Review is permitted only when the resolved chain state is a clean, readable result: a verified
 *  tip ("resolved") or a genuine absence of any record ("REVIEW_MISSING"). Every other state is a
 *  failed or invalid history and must keep the actions disabled, including a missing `state`. */
const REVIEW_STATE_PERMITS = new Set(["resolved", "REVIEW_MISSING"]);

export function reviewIsPermitted(review: ReviewView["review"]): boolean {
  return REVIEW_STATE_PERMITS.has(review.state);
}

/** The candidate changed between being shown and a confirm/reject: the review must be redone. */
export class ReviewStale extends Error {}

/** The review was saved, but reading its current status back failed. It IS recorded; reload before
 *  continuing. Never treated as "nothing changed" and never shown as current approval. */
export class ReviewStatusUnavailable extends Error {}

async function reviewResponse(response: Response): Promise<ReviewView> {
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (response.status === 409) {
    const said =
      typeof body === "object" && body !== null && "error" in body ? String(body.error) : "";
    throw new ReviewStale(said || "The candidate changed since it was shown; reload and review it again.");
  }
  if (response.ok && typeof body === "object" && body !== null && "status_unavailable" in body) {
    // The save succeeded but its status could not be read back: recorded, but reload before acting.
    throw new ReviewStatusUnavailable(
      "message" in body
        ? String((body as { message: unknown }).message)
        : "Your review was recorded, but its current status could not be loaded. Reload before continuing.",
    );
  }
  if (!response.ok || !body || typeof body !== "object") {
    const said =
      typeof body === "object" && body !== null && "error" in body ? String(body.error) : "";
    throw new LoadError(said || (isJson ? "The review could not be loaded." : SIGN_IN_ENDED), !isJson);
  }
  return body as ReviewView;
}

export async function loadReview(leadId: string, fetcher: typeof fetch = fetch): Promise<ReviewView> {
  if (import.meta.env.VITE_DEMO === "1") {
    const demo = await import("./demo/review");
    return demo.demoReview(leadId);
  }
  let response: Response;
  try {
    response = await fetcher(`/api/review/${encodeURIComponent(leadId)}`, {
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new LoadError("The console could not be reached. Check the connection and try again.");
  }
  return reviewResponse(response);
}

/** Record the reviewer's judgment. The reviewer identity is the signed-in session on the server;
 *  nothing here sends or drafts. `fingerprint` is echoed back so a candidate that changed since it
 *  was shown is refused (ReviewStale). */
export async function recordReview(
  leadId: string,
  decision: "confirm" | "reject",
  fingerprint: string,
  fetcher: typeof fetch = fetch,
): Promise<ReviewView> {
  if (import.meta.env.VITE_DEMO === "1") {
    const demo = await import("./demo/review");
    return demo.demoRecord(leadId, decision, fingerprint);
  }
  let response: Response;
  try {
    response = await fetcher(`/api/review/${encodeURIComponent(leadId)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json",
                 "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: JSON.stringify({ decision, fingerprint }),
    });
  } catch {
    throw new LoadError("The console could not be reached. Check the connection and try again.");
  }
  return reviewResponse(response);
}

// --- lead import (flag-gated on the server) ------------------------------------------------

/** Why an import step could not be done. `stale` means the preview no longer matches and must be
 *  redone; `uncertain` means a commit may or may not have been saved and the leads should be reloaded
 *  before trying again. */
export class ImportError extends Error {
  readonly stale: boolean;
  readonly uncertain: boolean;

  constructor(message: string, { stale = false, uncertain = false } = {}) {
    super(message);
    this.stale = stale;
    this.uncertain = uncertain;
  }
}

async function importBody(response: Response, whatFailed: string): Promise<unknown> {
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  const said = typeof body === "object" && body !== null && "error" in body ? String(body.error) : "";
  if (response.status === 409) throw new ImportError(said || "The preview is out of date. Preview again.", { stale: true });
  // 502 here is a DEFINITE "nothing was written; safe to retry" (an unconfirmed write is reported as a
  // 200 with outcome "uncertain", handled by the caller - never conflated with "nothing written").
  if (response.status === 502) throw new ImportError(said || `${whatFailed} could not be saved. Nothing was written.`);
  if (!response.ok || !body || typeof body !== "object") {
    throw new ImportError(said || (isJson ? `${whatFailed} could not be done.` : SIGN_IN_ENDED));
  }
  return body;
}

/** Preview an import from pasted text or an uploaded file. Nothing is written. */
export async function importPreview(
  input: { text?: string; file?: File; prefix: string },
  fetcher: typeof fetch = fetch,
): Promise<ImportPreview> {
  let request: RequestInit;
  if (input.file) {
    const form = new FormData();
    form.append("file", input.file);
    form.append("prefix", input.prefix);
    request = { method: "POST", body: form };
  } else {
    request = {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: input.text ?? "", prefix: input.prefix }),
    };
  }
  request.headers = { ...(request.headers ?? {}), Accept: "application/json", "X-Requested-With": "XMLHttpRequest" };
  request.credentials = "same-origin";
  let response: Response;
  try {
    response = await fetcher("/api/import/preview", request);
  } catch {
    throw new ImportError("The console could not be reached. Check the connection and try again.");
  }
  return (await importBody(response, "The preview")) as ImportPreview;
}

/** Confirm an import: append the accepted rows. The fingerprint binds them to the preview shown; the
 *  idempotency key makes a retry of the same confirm safe and lets independent instances be resolved to
 *  a single writer per lead. Reuse the SAME key when retrying the same confirmed import. */
export async function importCommit(
  prefix: string,
  rows: Record<string, string>[],
  fingerprint: string,
  idempotencyKey: string,
  fetcher: typeof fetch = fetch,
): Promise<ImportResult> {
  let response: Response;
  try {
    response = await fetcher("/api/import/commit", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      // Re-committing with the same idempotency key is read-only reconciliation: it reports what has
      // been written; it never takes over and writes a lead another attempt owns.
      body: JSON.stringify({ prefix, rows, fingerprint, idempotency_key: idempotencyKey }),
    });
  } catch {
    throw new ImportError("The console could not be reached. Check the connection and try again.");
  }
  return (await importBody(response, "The import")) as ImportResult;
}

// --- A/B experiments (flag-gated on the server) --------------------------------------------

/** Why an experiment action could not be saved, in words for the founder. */
export class ExperimentError extends Error {}

async function experimentBody<T>(response: Response, what: string): Promise<T> {
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok || !body || typeof body !== "object" || !("recorded" in body)) {
    const said = typeof body === "object" && body !== null && "error" in body ? String(body.error) : "";
    throw new ExperimentError(said || (isJson ? `${what} could not be saved just now.` : SIGN_IN_ENDED));
  }
  return body as T;
}

async function experimentPost<T>(path: string, payload: Record<string, unknown>, fetcher: typeof fetch): Promise<T> {
  let response: Response;
  try {
    response = await fetcher(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ExperimentError("The console could not be reached. Check the connection and try again.");
  }
  return experimentBody<T>(response, "The experiment");
}

/** Define an experiment's two named variants. Idempotent: the same definition saves nothing new. */
export function defineExperiment(
  input: { experiment: string; variant_a: string; variant_b: string },
  fetcher: typeof fetch = fetch,
): Promise<ExperimentDefineResult> {
  return experimentPost<ExperimentDefineResult>("/api/experiments/define", input, fetcher);
}

/** Assign every eligible, not-yet-assigned lead to a variant. A lead is assigned once and never moves. */
export function assignExperiment(
  input: { experiment: string },
  fetcher: typeof fetch = fetch,
): Promise<ExperimentAssignResult> {
  return experimentPost<ExperimentAssignResult>("/api/experiments/assign", input, fetcher);
}

// --- call tasks (flag-gated on the server) -------------------------------------------------

/** Why a call action could not be recorded, in words for the founder. */
export class CallError extends Error {}

async function callBody(response: Response): Promise<CallResult> {
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok || !body || typeof body !== "object" || !("recorded" in body)) {
    const said = typeof body === "object" && body !== null && "error" in body ? String(body.error) : "";
    throw new CallError(said || (isJson ? "That could not be recorded just now." : SIGN_IN_ENDED));
  }
  return body as CallResult;
}

async function callPost(path: string, payload: Record<string, unknown>, fetcher: typeof fetch): Promise<CallResult> {
  let response: Response;
  try {
    response = await fetcher(path, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: JSON.stringify(payload),
    });
  } catch {
    throw new CallError("The console could not be reached. Check the connection and try again.");
  }
  return callBody(response);
}

/** Record a call outcome for a lead; the server schedules the next call and returns the call state.
 *  `submission_id` is one logical submission's identity: retries of the same call carry it so the
 *  server records one row even when the UI omits the call time and a response is lost. */
export function recordCallOutcome(
  leadId: string,
  outcome: { outcome: string; note?: string; called_at?: string; callback_at?: string; submission_id?: string },
  fetcher: typeof fetch = fetch,
): Promise<CallResult> {
  return callPost(`/api/calls/${encodeURIComponent(leadId)}/outcome`, outcome, fetcher);
}

/** Upload a PDF/DOCX playbook and get its extracted text and review. Reads only; writes nothing. A rejected
 *  file (empty / too large / unsupported / malformed / image-only) throws CallError with the reason. */
export async function reviewPlaybook(file: File, fetcher: typeof fetch = fetch): Promise<PlaybookUpload> {
  const form = new FormData();
  form.append("file", file);
  let response: Response;
  try {
    response = await fetcher("/api/playbook/review", {
      method: "POST",
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: form,
    });
  } catch {
    throw new CallError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok || !body || typeof body !== "object" || !("review" in body)) {
    const said =
      typeof body === "object" && body !== null && ("error" in body)
        ? String((body as { error: unknown }).error)
        : "That playbook could not be read.";
    throw new CallError(said);
  }
  return body as PlaybookUpload;
}

/** The founder's explicit Select action: exchange a review token for a selection token at the server. Reads
 *  only; writes nothing. A version that was not reviewed (or whose review expired/changed) is refused. */
export async function selectPlaybook(
  choice: { text: string; review_token: string },
  fetcher: typeof fetch = fetch,
): Promise<PlaybookSelection> {
  let response: Response;
  try {
    response = await fetcher("/api/playbook/select", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: JSON.stringify(choice),
    });
  } catch {
    throw new CallError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok || !body || typeof body !== "object" || !("selection_token" in body)) {
    const said =
      typeof body === "object" && body !== null && "error" in body ? String((body as { error: unknown }).error) : "";
    throw new CallError(said || "The version could not be selected.");
  }
  return body as PlaybookSelection;
}

/** Preview a candidate follow-up from a selected playbook version (by selection token). Reads only; no
 *  Gmail, no Drive, no send. A version not selected (or whose selection changed/expired) is refused. */
export async function previewPlaybook(
  selection: { text: string; selection_token: string; first_name?: string },
  fetcher: typeof fetch = fetch,
): Promise<PlaybookPreview> {
  let response: Response;
  try {
    response = await fetcher("/api/playbook/preview", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: JSON.stringify(selection),
    });
  } catch {
    throw new CallError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok || !body || typeof body !== "object" || !("problems" in body)) {
    const said =
      typeof body === "object" && body !== null && "error" in body ? String((body as { error: unknown }).error) : "";
    throw new CallError(said || "The preview could not be built.");
  }
  return body as PlaybookPreview;
}

/** Interpret a typed call note into a proposal to confirm. Reads only; the server writes nothing here
 *  (the confirm goes through recordCallOutcome). `lead_id` chooses among several matches; `callback_at`
 *  supplies an explicit callback time. */
export async function interpretCallNote(
  note: string,
  refine: { lead_id?: string; callback_at?: string } = {},
  fetcher: typeof fetch = fetch,
): Promise<CallProposal> {
  let response: Response;
  try {
    response = await fetcher("/api/calls/interpret", {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: JSON.stringify({ note, ...refine }),
    });
  } catch {
    throw new CallError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok || !body || typeof body !== "object" || !("status" in body)) {
    const said = typeof body === "object" && body !== null && "error" in body ? String(body.error) : "";
    throw new CallError(said || "The note could not be read just now.");
  }
  return body as CallProposal;
}

/** Load the post-call email candidate for a lead (inspect / edit / discard). Reads only; the server
 *  never sends, drafts to Gmail, or persists. Returns the candidate or a reason it is not offered. */
export async function loadCallCandidate(
  leadId: string,
  fetcher: typeof fetch = fetch,
): Promise<CallCandidateResult> {
  let response: Response;
  try {
    response = await fetcher(`/api/calls/${encodeURIComponent(leadId)}/candidate`, {
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new CallError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok || !body || typeof body !== "object" || !("candidate" in body)) {
    throw new CallError("The post-call candidate could not be loaded.");
  }
  return body as CallCandidateResult;
}

/** Load the reply-draft candidate for a lead (inspect / edit / discard) after it wrote back. Reads only;
 *  the server never sends, drafts to Gmail, or persists. Returns the candidate or a reason it is not offered. */
export async function loadReplyCandidate(
  leadId: string,
  fetcher: typeof fetch = fetch,
): Promise<ReplyCandidateResult> {
  let response: Response;
  try {
    response = await fetcher(`/api/reply/${encodeURIComponent(leadId)}/candidate`, {
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch {
    throw new CallError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const body: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok || !body || typeof body !== "object" || !("candidate" in body)) {
    throw new CallError("The reply candidate could not be loaded.");
  }
  return body as ReplyCandidateResult;
}

/** Create the reviewed reply as an in-thread Gmail DRAFT (the founder sends it by hand). Throws CallError
 *  with the server's reason when the draft is refused (a call stop, suppression, drafts disabled, a draft
 *  already in the thread, …). The server never sends. */
export async function createReplyDraft(
  leadId: string,
  subject: string,
  body: string,
  fetcher: typeof fetch = fetch,
): Promise<{ created: boolean; draft_id: string; thread_id: string }> {
  let response: Response;
  try {
    response = await fetcher(`/api/reply/${encodeURIComponent(leadId)}/draft`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
      body: JSON.stringify({ subject, body }),
    });
  } catch {
    throw new CallError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const payload: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok) {
    const said =
      payload && typeof payload === "object" && "error" in payload ? String((payload as { error: unknown }).error) : "";
    throw new CallError(said || "The reply draft could not be created.");
  }
  return payload as { created: boolean; draft_id: string; thread_id: string };
}

export interface SendResult {
  lead_id: string;
  sent: boolean;
  message_id: string;
  thread_id: string;
  recorded: boolean;
  sent_by: string;
}

/** POST /api/send/<lead>: send the already-created Gmail draft for this lead, on the founder's
 *  approval. One click sends exactly one email; the server refuses (409) an uncreated or already-sent
 *  lead, so a repeat never sends twice. */
export async function sendDraft(leadId: string, fetcher: typeof fetch = fetch): Promise<SendResult> {
  let response: Response;
  try {
    response = await fetcher(`/api/send/${encodeURIComponent(leadId)}`, {
      method: "POST",
      headers: { Accept: "application/json", "X-Requested-With": "XMLHttpRequest" },
      credentials: "same-origin",
    });
  } catch {
    throw new CallError("The console could not be reached. Check the connection and try again.");
  }
  if (response.status === 401) throw new LoadError(SIGN_IN_ENDED, true);
  const isJson = (response.headers.get("Content-Type") ?? "").includes("application/json");
  const payload: unknown = isJson ? await response.json().catch(() => null) : null;
  if (!response.ok) {
    const said =
      payload && typeof payload === "object" && "error" in payload ? String((payload as { error: unknown }).error) : "";
    throw new CallError(said || "The email could not be sent.");
  }
  return payload as SendResult;
}

/** Complete, snooze or cancel a lead's call task. `task_id` is required and names the exact task the
 *  founder was shown, so an action can never fall back to whatever task is open now: a stale id is
 *  refused (409) and a missing one is refused (400), and neither touches a newer task. */
export function actOnCallTask(
  leadId: string,
  action: { action: string; task_id: string; snooze_to?: string },
  fetcher: typeof fetch = fetch,
): Promise<CallResult> {
  return callPost(`/api/calls/${encodeURIComponent(leadId)}/task`, action, fetcher);
}

/** The name of the script this page is running, e.g. "index-a1b2c3.js". The server says which
 *  it has; when the two differ, the page in front of the founder is out of date. */
export function runningBuild(): string {
  try {
    return new URL(import.meta.url).pathname.split("/").pop() ?? "";
  } catch {
    return "";
  }
}
