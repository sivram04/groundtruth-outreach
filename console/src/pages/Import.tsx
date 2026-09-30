import { Check, FileUp, Upload } from "lucide-react";
import { useState } from "react";
import { ImportError, importCommit, importPreview } from "../api";
import { Card, Chip, PageHead, Status, type Tone } from "../components";
import type { ImportPreview } from "../types";

type Previewer = typeof importPreview;
type Committer = typeof importCommit;

const CHANNEL_TONE: Record<string, Tone> = { EMAIL: "green", CALL: "amber", COMPANY_ONLY: "gray" };
const CHANNEL_LABEL: Record<string, string> = {
  EMAIL: "Email", CALL: "Call", COMPANY_ONLY: "No contact",
};

/** Import a small list of leads: paste or upload it, see exactly what would be stored (and what
 *  cannot be), confirm once, and the leads then appear on reload. Only new rows are written; the
 *  founder's existing rows are never touched. Preview and commit are injectable for tests. */
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
  const [result, setResult] = useState<{ written: number; already: number; ids: string[] } | null>(null);
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
        setBusy(false);
      },
      (e: unknown) => {
        setError(e instanceof Error ? e.message : "The preview could not be done.");
        setBusy(false);
      },
    );
  }

  function onConfirm() {
    if (busy || !preview || result) return;  // one confirm only
    setBusy(true);
    setError("");
    const rows = preview.accepted.map((item) => item.row);
    doCommit(preview.prefix, rows, preview.fingerprint).then(
      (r) => {
        setResult({ written: r.written, already: r.already_present, ids: r.lead_ids });
        setBusy(false);
        onImported();  // reload the snapshot so the new leads show
      },
      (e: unknown) => {
        setBusy(false);
        if (e instanceof ImportError && e.stale) {
          // the preview no longer matches; it must be redone before anything is written
          setPreview(null);
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
        <Card title="Imported">
          <p>
            {result.written > 0
              ? `Imported ${result.written} lead${result.written === 1 ? "" : "s"}${result.ids.length ? ` (${result.ids.join(", ")})` : ""}.`
              : "No new leads were added."}
            {result.already > 0 && ` ${result.already} were already present.`}
          </p>
          <div className="email-actions">
            <a className="primary" href="#/leads">View the leads</a>
            <button type="button" className="secondary" onClick={() => { setText(""); setFile(null); reset(); }}>
              Import another list
            </button>
          </div>
        </Card>
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
                        {Object.entries(item.row).map(([column, value]) => (
                          <span key={column} className="field"><strong>{column}:</strong> {value} </span>
                        ))}
                        {item.unstorable.length > 0 && (
                          <span className="unstorable">
                            {" "}⚠ not stored: {item.unstorable.map((u) => `${u.field} (${u.value})`).join(", ")}
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
                  <li key={index}><span>{s.reason}</span></li>
                ))}
              </ul>
            </Card>
          )}

          <Card title="Confirm">
            <p className="muted small">
              Only new rows are added to tab {preview.prefix}; your existing rows are never changed.
            </p>
            <div className="email-actions">
              <button type="button" className="primary" disabled={busy || preview.accepted.length === 0} onClick={onConfirm}>
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
