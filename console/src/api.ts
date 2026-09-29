import type { Snapshot } from "./types";

export const EXPECTED_VERSION = 1;

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
