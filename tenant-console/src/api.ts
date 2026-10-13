import type { AutoRunResult, DraftPreview, SessionState } from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json", Accept: "application/json" },
      ...init,
    });
  } catch {
    throw new ApiError("The server could not be reached. Check the connection and try again.", 0);
  }
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    // A non-JSON response (e.g. a 500 from an unhandled error) still needs a message.
  }
  if (!response.ok) {
    const message =
      body && typeof body === "object" && "error" in body && typeof body.error === "string"
        ? body.error
        : `Something went wrong (${response.status}).`;
    throw new ApiError(message, response.status);
  }
  return body as T;
}

export const config = () => call<{ google_client_id: string }>("/api/config");

export const currentSession = () => call<SessionState>("/api/session");

export const signIn = (credential: string) =>
  call<SessionState & { account_id: string; name: string; email: string }>("/api/session/google", {
    method: "POST",
    body: JSON.stringify({ credential }),
  });

export const switchAccount = (accountId: string) =>
  call<SessionState>("/api/session/switch", {
    method: "POST",
    body: JSON.stringify({ account_id: accountId }),
  });

export const logout = (options: { accountId?: string; all?: boolean } = {}) =>
  call<SessionState>("/api/session/logout", {
    method: "POST",
    body: JSON.stringify({ account_id: options.accountId, all: options.all }),
  });

export const connectStart = (kind: "gmail" | "drive") =>
  call<{ authorization_url: string }>(`/api/connections/${kind}/start`, { method: "POST" });

export const connections = () => call<{ gmail: boolean; drive: boolean }>("/api/account/connections");

export const disconnect = (kind: "gmail" | "drive") =>
  call<{ ok: true }>(`/api/connections/${kind}`, { method: "DELETE" });

export const getSheet = () => call<{ sheet_id: string | null }>("/api/account/sheet");

export const linkSheet = (sheetId?: string) =>
  call<{ sheet_id: string }>("/api/account/sheet", {
    method: "POST",
    body: JSON.stringify(sheetId ? { sheet_id: sheetId } : {}),
  });

export const unlinkSheet = () => call<{ ok: true }>("/api/account/sheet", { method: "DELETE" });

export interface LeadTabsResult {
  lead_tabs: Record<string, string>;
  is_custom: boolean;
}

export const getLeadTabs = () => call<LeadTabsResult>("/api/account/lead-tabs");

export const setLeadTabs = (leadTabs: Record<string, string>) =>
  call<LeadTabsResult>("/api/account/lead-tabs", {
    method: "PUT",
    body: JSON.stringify({ lead_tabs: leadTabs }),
  });

export const clearLeadTabs = () => call<LeadTabsResult>("/api/account/lead-tabs", { method: "DELETE" });

export const runAuto = () => call<AutoRunResult>("/api/jobs/auto", { method: "POST" });

export const previewDrafts = (ids: string[]) =>
  call<{ previews: DraftPreview[] }>("/api/jobs/draft/preview", {
    method: "POST",
    body: JSON.stringify({ ids }),
  });

export const createDraft = (leadId: string, approvedHash: string, written: unknown) =>
  call<{ lead_id: string; draft_id: string; status: string }>("/api/jobs/draft/create", {
    method: "POST",
    body: JSON.stringify({ lead_id: leadId, approved_hash: approvedHash, written }),
  });
