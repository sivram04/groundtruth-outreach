import type { Snapshot } from "./types";

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
  review: { decision: string | null; reviewer?: string; reviewed_at?: string; current: boolean };
  note: string;
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

/** The name of the script this page is running, e.g. "index-a1b2c3.js". The server says which
 *  it has; when the two differ, the page in front of the founder is out of date. */
export function runningBuild(): string {
  try {
    return new URL(import.meta.url).pathname.split("/").pop() ?? "";
  } catch {
    return "";
  }
}
