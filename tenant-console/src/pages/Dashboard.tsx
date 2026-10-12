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

function connectRedirectNotice(): { kind: "ok" | "error"; text: string } | null {
  // The OAuth callback is a page navigation (Google's own redirect), not a fetch() call, so it
  // sends the outcome back as a query string on "/" rather than a JSON body nothing would read.
  const params = new URLSearchParams(window.location.search);
  const connected = params.get("connected");
  const error = params.get("connect_error");
  if (!connected && !error) return null;
  window.history.replaceState({}, "", window.location.pathname);
  if (error) return { kind: "error", text: error };
  return { kind: "ok", text: `${connected === "gmail" ? "Gmail" : "Sheets"} connected.` };
}

function ConnectCard({ account_id }: { account_id?: string }) {
  const [error, setError] = useState("");
  const [notice, setNotice] = useState(connectRedirectNotice);
  const [status, setStatus] = useState<{ gmail: boolean; drive: boolean } | null>(null);
  const [busyKind, setBusyKind] = useState<"gmail" | "drive" | null>(null);

  const load = useCallback(async () => {
    try {
      setStatus(await api.connections());
    } catch {
      setStatus(null);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load, account_id]);

  const start = async (kind: "gmail" | "drive") => {
    setError("");
    try {
      const { authorization_url: url } = await api.connectStart(kind);
      window.location.href = url;
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start the connection.");
    }
  };

  const stop = async (kind: "gmail" | "drive") => {
    setError("");
    setBusyKind(kind);
    try {
      await api.disconnect(kind);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not disconnect.");
    } finally {
      setBusyKind(null);
    }
  };

  const row = (kind: "gmail" | "drive", label: string) => {
    const on = status?.[kind];
    return (
      <div className="row" style={{ marginBottom: 6 }}>
        <span className={`pill${on ? " pill-active" : ""}`}>{on ? "Connected" : "Not connected"}</span>
        {on ? (
          <button className="btn btn-ghost" onClick={() => stop(kind)} disabled={busyKind === kind}>
            Disconnect {label}
          </button>
        ) : (
          <button className="btn" onClick={() => start(kind)}>
            Connect {label}
          </button>
        )}
      </div>
    );
  };

  return (
    <div className="card">
      <h2>Connect Google</h2>
      <p>Grant this account's own Gmail (to draft) and Sheets (to read/write leads) access.</p>
      {notice && (
        <div className={`notice ${notice.kind === "ok" ? "notice-ok" : "notice-error"}`}>
          {notice.text}
          <button className="btn btn-ghost" style={{ float: "right" }} onClick={() => setNotice(null)}>
            ×
          </button>
        </div>
      )}
      {error && <div className="notice notice-error">{error}</div>}
      {row("gmail", "Gmail")}
      {row("drive", "Sheets")}
    </div>
  );
}

function SheetCard({ sheetId, onLinked }: { sheetId: string | null; onLinked: (id: string | null) => void }) {
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

  const unlink = async () => {
    setBusy(true);
    setError("");
    try {
      await api.unlinkSheet();
      onLinked(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not unlink the Sheet.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="card">
      <h2>Your leads Sheet</h2>
      {error && <div className="notice notice-error">{error}</div>}
      {sheetId ? (
        <div className="row">
          <p style={{ margin: 0 }}>
            Connected:{" "}
            <a href={`https://docs.google.com/spreadsheets/d/${sheetId}/edit`} target="_blank" rel="noreferrer">
              open in Google Sheets
            </a>
          </p>
          <button className="btn btn-ghost" onClick={unlink} disabled={busy}>
            Unlink
          </button>
        </div>
      ) : (
        <>
          <p>Create a brand-new Sheet, or link one you already have (Connect Sheets first).</p>
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
      <ConnectCard account_id={session.account_id} />
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
