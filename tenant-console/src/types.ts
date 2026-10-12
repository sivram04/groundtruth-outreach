export interface AccountInfo {
  account_id: string;
  email: string;
  name: string;
  active: boolean;
}

export interface SessionState {
  signed_in: boolean;
  account_id?: string;
  accounts: AccountInfo[];
}

export interface JobCounts {
  [key: string]: unknown;
}

export interface AutoRunResult {
  checked: JobCounts;
  researched: JobCounts;
  profiled: JobCounts;
}

export interface DraftPreview {
  lead_id: string;
  company: string;
  to: string;
  subject: string;
  body: string;
  blockers: string[];
  preview_hash: string | null;
  [key: string]: unknown;
}
