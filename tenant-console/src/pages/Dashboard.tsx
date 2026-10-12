import { useCallback, useEffect, useState } from "react";
import * as api from "../api";
import type { AccountInfo, AutoRunResult, DraftPreview, SessionState } from "../types";

function AccountBar({
  session,
  onSwitch,
  onSignInAnother,
  onLogout,
}: {
  session: SessionState;
  onSwitch: (id: string) => void;
  onSignInAnother: () => void;
  onLogout: () => void;
}) {
  return (
    <div className="topbar">
      <div className="brand">Outreach</div>
      <div className="accounts">
        {session.accounts.map((a: AccountInfo) => (
          <button
            key={a.account_id}
            className={`pill${a.active ? " pill-active" : ""}`}
            onClick={() => onSwitch(a.account_id)}
            disabled={a.active}
          >
            {a.email}
          </button>
        ))}
        <button className="btn btn-ghost" onClick={onSignInAnother}>
          + Add account
        </button>
        <button className="btn btn-ghost" onClick={onLogout}>
          Sign out
        </button>
      </div>
    </div>
  );
}

function ConnectCard() {
  const [error, setError] = useState("");

  const start = async (kind: "gmail" | "drive") => {
    setError("");
    try {
      const { authorization_url: url } = await api.connectStart(kind);
      window.location.href = url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the connection.");
    }
  };

  return (
    <div className="card">
      <h2>Connect Google</h2>
      <p>Grant this account's own Gmail (to draft) and Sheets (to read/write leads) access.</p>
      {error && <div className="notice notice-error">{error}</div>}
      <div className="row">
        <button className="btn" onClick={() => start("gmail")}>
          Connect Gmail
        </button>
        <button className="btn" onClick={() => start("drive")}>
          Connect Sheets
        </button>
      </div>
    </div>
  );
}

function SheetCard({ sheetId, onLinked }: { sheetId: string | null; onLinked: (id: string) => void }) {
  const [linkId, setLinkId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const link = async (useExisting: boolean) => {
    setBusy(true);
    setError("");
    try {
      const result = await api.linkSheet(useExisting ? linkId : undefined);
      onLinked(result.sheet_id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not set up the Sheet.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>Your leads Sheet</h2>
      {sheetId ? (
        <p>
          Connected:{" "}
          <a href={`https://docs.google.com/spreadsheets/d/${sheetId}/edit`} target="_blank" rel="noreferrer">
            open in Google Sheets
          </a>
        </p>
      ) : (
        <>
          <p>Create a brand-new Sheet, or link one you already have (Connect Sheets first).</p>
          {error && <div className="notice notice-error">{error}</div>}
          <div className="row" style={{ marginBottom: 8 }}>
            <button className="btn btn-primary" onClick={() => link(false)} disabled={busy}>
              Create a new Sheet
            </button>
          </div>
          <div className="row">
            <input
              type="text"
              placeholder="Or paste an existing Sheet ID"
              value={linkId}
              onChange={(e) => setLinkId(e.target.value)}
            />
            <button className="btn" onClick={() => link(true)} disabled={busy || !linkId.trim()}>
              Link it
            </button>
          </div>
        </>
      )}
    </div>
  );
}

function JobsCard({ sheetReady }: { sheetReady: boolean }) {
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<AutoRunResult | null>(null);
  const [error, setError] = useState("");

  const run = async () => {
    setRunning(true);
    setError("");
    setResult(null);
    try {
      setResult(await api.runAuto());
    } catch (err) {
      setError(err instanceof Error ? err.message : "The run failed.");
    } finally {
      setRunning(false);
    }
  };

  return (
    <div className="card">
      <h2>Check, research and profile your leads</h2>
      <p>Runs the same three stages the single-tenant pipeline does, against your own Sheet.</p>
      {error && <div className="notice notice-error">{error}</div>}
      <button className="btn btn-primary" onClick={run} disabled={!sheetReady || running}>
        {running ? "Running..." : "Run now"}
      </button>
      {result && (
        <pre style={{ marginTop: 12 }}>{JSON.stringify(result, null, 2)}</pre>
      )}
    </div>
  );
}

function DraftsCard({ sheetReady }: { sheetReady: boolean }) {
  const [ids, setIds] = useState("");
  const [previews, setPreviews] = useState<DraftPreview[] | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const preview = async () => {
    const leadIds = ids
      .split(",")
      .map((s) => s.trim())
      .filter(Boolean);
    if (!leadIds.length) return;
    setBusy(true);
    setError("");
    setPreviews(null);
    try {
      const { previews: result } = await api.previewDrafts(leadIds);
      setPreviews(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not preview those leads.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>Preview a draft email</h2>
      <p>Up to 4 Lead IDs, comma-separated (e.g. A-0001, A-0002).</p>
      {error && <div className="notice notice-error">{error}</div>}
      <div className="row">
        <input type="text" placeholder="A-0001, A-0002" value={ids} onChange={(e) => setIds(e.target.value)} />
        <button className="btn" onClick={preview} disabled={!sheetReady || busy || !ids.trim()}>
          Preview
        </button>
      </div>
      {previews?.map((p) => (
        <div className="lead-preview" key={p.lead_id}>
          <h3>
            {p.lead_id} — {p.company || "(no company)"}
          </h3>
          {p.blockers.length > 0 ? (
            <div className="notice notice-error">{p.blockers.join("; ")}</div>
          ) : (
            <div className="notice notice-ok">Ready — no blockers</div>
          )}
          {p.subject && <p>Subject: {p.subject}</p>}
        </div>
      ))}
    </div>
  );
}

export function Dashboard({
  session,
  refresh,
  onAddAccount,
}: {
  session: SessionState;
  refresh: () => void;
  onAddAccount: () => void;
}) {
  const [sheetId, setSheetId] = useState<string | null>(null);
  const [loadingSheet, setLoadingSheet] = useState(true);

  const loadSheet = useCallback(async () => {
    setLoadingSheet(true);
    try {
      const { sheet_id: id } = await api.getSheet();
      setSheetId(id);
    } finally {
      setLoadingSheet(false);
    }
  }, []);

  useEffect(() => {
    loadSheet();
  }, [loadSheet, session.account_id]);

  const switchAccount = async (id: string) => {
    await api.switchAccount(id);
    refresh();
  };

  const logout = async () => {
    await api.logout({ accountId: session.account_id });
    refresh();
  };

  return (
    <div className="shell">
      <AccountBar session={session} onSwitch={switchAccount} onSignInAnother={onAddAccount} onLogout={logout} />
      <ConnectCard />
      <SheetCard sheetId={sheetId} onLinked={(id) => setSheetId(id)} />
      {!loadingSheet && (
        <>
          <JobsCard sheetReady={Boolean(sheetId)} />
          <DraftsCard sheetReady={Boolean(sheetId)} />
        </>
      )}
    </div>
  );
}
