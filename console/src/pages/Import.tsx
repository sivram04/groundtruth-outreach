import { Check, FileUp, RotateCw, Upload } from "lucide-react";
import { useState } from "react";
import { ImportError, importCommit, importPreview } from "../api";
import { Card, Chip, PageHead, Status, type Tone } from "../components";
import type { ImportPreview, ImportResult } from "../types";

type Previewer = typeof importPreview;
type Committer = typeof importCommit;

const CHANNEL_TONE: Record<string, Tone> = { EMAIL: "green", CALL: "amber", COMPANY_ONLY: "gray" };
const CHANNEL_LABEL: Record<string, string> = {
  EMAIL: "Email", CALL: "Call", COMPANY_ONLY: "No contact",
};

function newKey() {
  try {
    return crypto.randomUUID();
  } catch {
    return `k-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

// A durable operation key per previewed list (by its fingerprint), kept in this browser so a reload of
// the same list resumes the SAME import operation rather than starting a fresh competing one.
function keyFor(fingerprint: string): string {
  const at = `outreach.import.${fingerprint}`;
  try {
    const existing = window.localStorage.getItem(at);
    if (existing) return existing;
    const fresh = newKey();
    window.localStorage.setItem(at, fresh);
    return fresh;
  } catch {
    return newKey();
  }
}

/** Import a small list of leads: paste or upload it, see exactly what would be stored (and what
 *  cannot be), confirm once, and the leads then appear on reload. Only new rows are written; the
 *  founder's existing rows are never touched. Pending, blocked and uncertain outcomes are shown
 *  honestly - never as a completed import. Preview and commit are injectable for tests. */
export function Import({
  onImported,
  preview: doPreview = importPreview,
  commit: doCommit = importCommit,
}: {
  onImported: () => void;
  preview?: Previewer;
  commit?: Committer;
}) {
  const [text, setText] = useState("");
  const [file, setFile] = useState<File | null>(null);
  const [prefix, setPrefix] = useState("A");
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [key, setKey] = useState("");
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  function reset() {
    setPreview(null);
    setResult(null);
    setError("");
  }

  function onPreview() {
    if (busy) return;
    setBusy(true);
    reset();
    doPreview(file ? { file, prefix } : { text, prefix }).then(
      (p) => {
        setPreview(p);
        setKey(keyFor(p.fingerprint));  // durable op key for this list; reused on resume/reload
        setBusy(false);
      },
      (e: unknown) => {
        setError(e instanceof Error ? e.message : "The preview could not be done.");
        setBusy(false);
      },
    );
  }

  function submit(resume: boolean) {
    if (busy || !preview) return;
    setBusy(true);
    setError("");
    const rows = preview.accepted.map((item) => item.row);
    doCommit(preview.prefix, rows, preview.fingerprint, key, { resume }).then(
      (r) => {
        setResult(r);
        setBusy(false);
        onImported();  // reload the snapshot so any written leads show
      },
      (e: unknown) => {
        setBusy(false);
        if (e instanceof ImportError && e.stale) {
          setPreview(null);  // the preview no longer matches; it must be redone before any write
          setResult(null);
        }
        setError(e instanceof Error ? e.message : "The import could not be confirmed.");
      },
    );
  }

  const summary = preview?.summary;
  return (
    <>
      <PageHead title="Import leads" sub="Paste or upload a small list. You will see exactly what would be stored before anything is saved." />

      {result ? (
        <Result result={result} busy={busy} onResume={() => submit(true)} onCheck={() => submit(false)}
                onAnother={() => { setText(""); setFile(null); reset(); }} />
      ) : (
        <Card title="The list">
          <label className="block small muted" htmlFor="import-text">Paste rows (CSV or tab-separated), with a header line</label>
          <textarea
            id="import-text"
            className="import-text"
            rows={6}
            value={text}
            placeholder={"Company,Contact,Email,Phone,Website\nAcme,Pat Lee,pat@acme.test,,https://acme.test"}
            onChange={(e) => { setText(e.target.value); setFile(null); }}
          />
          <div className="import-controls">
            <label className="file-choose">
              <FileUp size={15} aria-hidden="true" /> {file ? file.name : "or choose a .csv / .tsv / .xlsx file"}
              <input
                type="file"
                accept=".csv,.tsv,.xlsx"
                onChange={(e) => setFile(e.target.files?.[0] ?? null)}
              />
            </label>
            <label className="small">
              Into tab{" "}
              <select value={prefix} onChange={(e) => setPrefix(e.target.value)}>
                <option value="A">A</option>
                <option value="B">B</option>
              </select>
            </label>
            <button type="button" className="primary" disabled={busy || (!text.trim() && !file)} onClick={onPreview}>
              <Upload size={15} aria-hidden="true" /> Preview
            </button>
          </div>
        </Card>
      )}

      {error && (
        <div className="callout amber" role="alert">
          <div className="callout-text">{error}</div>
        </div>
      )}

      {preview && !result && (
        <>
          <Card title="What would be stored">
            <p className="muted small">
              {summary?.accepted ?? 0} to add · {summary?.duplicates ?? 0} already present ·{" "}
              {summary?.skipped ?? 0} skipped
              {summary && summary.unstorable > 0 && ` · ${summary.unstorable} field(s) cannot be stored`}
              {summary && summary.invalid > 0 && ` · ${summary.invalid} value(s) cannot be used`}
            </p>
            {preview.accepted.length === 0 ? (
              <p className="muted">Nothing new to import from this list.</p>
            ) : (
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Lead ID</th>
                    <th scope="col">How to reach</th>
                    <th scope="col">Fields</th>
                  </tr>
                </thead>
                <tbody>
                  {preview.accepted.map((item) => (
                    <tr key={item.lead_id}>
                      <td className="small">{item.lead_id}</td>
                      <td><Status tone={CHANNEL_TONE[item.channel] ?? "gray"}>{CHANNEL_LABEL[item.channel] ?? item.channel}</Status></td>
                      <td className="small">
                        {Object.entries(item.row)
                          .filter(([column]) => column !== "Lead ID")  // shown in its own column already
                          .map(([column, value]) => (
                            <span key={column} className="field"><strong>{column}:</strong> {value} </span>
                          ))}
                        {item.unstorable.length > 0 && (
                          <span className="unstorable">
                            {" "}⚠ not stored: {item.unstorable.map((u) => `${u.field} (${u.value})`).join(", ")}
                          </span>
                        )}
                        {item.invalid.length > 0 && (
                          <span className="unstorable">
                            {" "}⚠ cannot use: {item.invalid.map((u) => `${u.field} "${u.value}" — ${u.reason}`).join("; ")}
                          </span>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
            {preview.unstorable_fields.length > 0 && (
              <p className="unstorable small">
                These fields have no column in tab {preview.prefix} and will not be stored:{" "}
                {preview.unstorable_fields.join(", ")}. Add a column with that name first if you need them.
              </p>
            )}
          </Card>

          {preview.duplicates.length > 0 && (
            <Card title={`Already present (${preview.duplicates.length})`}>
              <ul className="mini-list">
                {preview.duplicates.map((d, index) => (
                  <li key={index}>
                    <Chip tone="gray">{d.matched}</Chip>
                    <span>{d.record.Company || d.record.company || d.record.Email || "a row"} — {d.reason}</span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          {preview.skipped.length > 0 && (
            <Card title={`Skipped (${preview.skipped.length})`}>
              <ul className="mini-list">
                {preview.skipped.map((s, index) => (
                  <li key={index}>
                    <span>
                      {s.reason}
                      {s.invalid && s.invalid.length > 0 && (
                        <span className="unstorable">
                          {" "}(supplied: {s.invalid.map((u) => `${u.field} "${u.value}" — ${u.reason}`).join("; ")})
                        </span>
                      )}
                    </span>
                  </li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="Confirm">
            <p className="muted small">
              Only new rows are added to tab {preview.prefix}; your existing rows are never changed.
            </p>
            <div className="email-actions">
              <button type="button" className="primary" disabled={busy || preview.accepted.length === 0} onClick={() => submit(false)}>
                <Check size={15} aria-hidden="true" /> {busy ? "Importing…" : `Import ${preview.accepted.length} lead${preview.accepted.length === 1 ? "" : "s"}`}
              </button>
              <button type="button" className="secondary" disabled={busy} onClick={reset}>Cancel</button>
            </div>
          </Card>
        </>
      )}
    </>
  );
}

/** The commit result, shown by its outcome. A pending, blocked or uncertain import is never presented
 *  as completed; each says what it means and offers the right next step. */
function Result({
  result,
  busy,
  onResume,
  onCheck,
  onAnother,
}: {
  result: ImportResult;
  busy: boolean;
  onResume: () => void;
  onCheck: () => void;
  onAnother: () => void;
}) {
  const written = result.written ?? 0;
  const wrote = written > 0 ? `Imported ${written} lead${written === 1 ? "" : "s"}${result.lead_ids?.length ? ` (${result.lead_ids.join(", ")})` : ""}.` : "";
  const already = result.already_present ? ` ${result.already_present} were already present.` : "";
  const viewLeads = <a className="primary" href="#/leads">View the leads</a>;
  const another = (
    <button type="button" className="secondary" onClick={onAnother}>Import another list</button>
  );

  if (result.outcome === "pending") {
    return (
      <Card title="Not finished yet">
        <p>
          {wrote || "Nothing was written yet."} An earlier attempt of this import owns {result.pending ?? 0}{" "}
          lead{(result.pending ?? 0) === 1 ? "" : "s"} and has not finished — it may still be running or it
          may have stopped. This is <strong>not</strong> a completed import.
        </p>
        <div className="email-actions">
          <button type="button" className="primary" disabled={busy} onClick={onResume}>
            <RotateCw size={15} aria-hidden="true" /> {busy ? "Resuming…" : "Resume this import"}
          </button>
          {another}
        </div>
      </Card>
    );
  }
  if (result.outcome === "uncertain") {
    return (
      <Card title="Outcome uncertain">
        <p>
          {result.message || "The import could not be confirmed — it may or may not have saved."} Reload the
          leads to check. Confirming again is safe: rows already saved are not added twice.
        </p>
        <div className="email-actions">
          {viewLeads}
          <button type="button" className="secondary" disabled={busy} onClick={onCheck}>
            <RotateCw size={15} aria-hidden="true" /> {busy ? "Checking…" : "Check again"}
          </button>
        </div>
      </Card>
    );
  }
  if (result.outcome === "blocked") {
    return (
      <Card title="Being imported elsewhere">
        <p>
          {result.claimed_elsewhere ?? 0} lead{(result.claimed_elsewhere ?? 0) === 1 ? "" : "s"} on this list
          {(result.claimed_elsewhere ?? 0) === 1 ? " is" : " are"} being imported by another submission, so
          {(result.claimed_elsewhere ?? 0) === 1 ? " it was" : " they were"} not imported here.
        </p>
        <div className="email-actions">{viewLeads}{another}</div>
      </Card>
    );
  }
  // done
  return (
    <Card title="Imported">
      <p>
        {wrote || "No new leads were added."}
        {already}
        {result.claimed_elsewhere ? ` ${result.claimed_elsewhere} were being imported by another submission.` : ""}
      </p>
      <div className="email-actions">{viewLeads}{another}</div>
    </Card>
  );
}
