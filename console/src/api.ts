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

/** The name of the script this page is running, e.g. "index-a1b2c3.js". The server says which
 *  it has; when the two differ, the page in front of the founder is out of date. */
export function runningBuild(): string {
  try {
    return new URL(import.meta.url).pathname.split("/").pop() ?? "";
  } catch {
    return "";
  }
}
