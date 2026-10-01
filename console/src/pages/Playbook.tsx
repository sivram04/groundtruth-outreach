import { BookOpen, Check, FileUp } from "lucide-react";
import { useRef, useState } from "react";
import { CallError, previewPlaybook, reviewPlaybook } from "../api";
import { Card, Status } from "../components";
import type { PlaybookPreview, PlaybookUpload } from "../types";

/** Upload a PDF/DOCX playbook, inspect its extracted text and identified sections, select an immutable
 *  version by content hash, and preview a candidate follow-up from it. Read-only and LOCAL: nothing is sent,
 *  no Gmail draft is made, and the production Drive handbook is untouched. The uploaded text is shown as
 *  data, never rendered as HTML and never run as instructions. `review`/`preview` are injectable for tests. */
export function Playbook({
  review = reviewPlaybook,
  preview = previewPlaybook,
}: {
  review?: typeof reviewPlaybook;
  preview?: typeof previewPlaybook;
}) {
  const [upload, setUpload] = useState<PlaybookUpload | null>(null);
  const [selectedHash, setSelectedHash] = useState("");
  const [firstName, setFirstName] = useState("");
  const [candidate, setCandidate] = useState<PlaybookPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fileRef = useRef<HTMLInputElement>(null);

  function onFile(file: File | undefined) {
    if (!file || busy) return;
    setBusy(true);
    setError("");
    setUpload(null);
    setSelectedHash("");
    setCandidate(null);
    review(file).then(
      (u) => {
        setBusy(false);
        setUpload(u);
      },
      (e: unknown) => {
        setBusy(false);
        setError(e instanceof CallError ? e.message : "That playbook could not be read.");
      },
    );
  }

  function runPreview() {
    if (!upload || busy) return;
    setBusy(true);
    setError("");
    setCandidate(null);
    preview({ text: upload.text, selection_token: upload.selection_token, first_name: firstName }).then(
      (p) => {
        setBusy(false);
        setCandidate(p);
      },
      (e: unknown) => {
        setBusy(false);
        setError(e instanceof CallError ? e.message : "The preview could not be built.");
      },
    );
  }

  const r = upload?.review;
  const selected = Boolean(upload && selectedHash === upload.review.content_hash);

  return (
    <>
      <h1 className="off-screen">Playbook</h1>
      <Card title="Upload a playbook" icon={FileUp}>
        <p className="small muted">
          Upload a PDF or DOCX. I will show the extracted text and the initial-email, follow-up and timing
          rules I can find, then you can select that exact version and preview a candidate. Nothing is sent,
          no email is drafted, and your production handbook is untouched.
        </p>
        <input
          ref={fileRef}
          type="file"
          accept=".pdf,.docx"
          onChange={(e) => onFile(e.target.files?.[0])}
          aria-label="Playbook file"
        />
        {busy && <p className="small muted loading">Reading…</p>}
        {error && (
          <div className="callout amber" role="alert">
            <div className="callout-text">{error}</div>
          </div>
        )}
      </Card>

      {r && (
        <Card title="What I found" icon={BookOpen}>
          <div className="chips">
            <Status tone={r.initial_email.present ? "green" : "amber"}>
              Initial email {r.initial_email.present ? "found" : "missing"}
            </Status>
            <Status tone={r.follow_ups["1"]?.present ? "green" : "amber"}>
              Follow-up 1 {r.follow_ups["1"]?.present ? "found" : "missing"}
            </Status>
            <Status tone={r.follow_ups["2"]?.present ? "green" : "amber"}>
              Follow-up 2 {r.follow_ups["2"]?.present ? "found" : "missing"}
            </Status>
            <Status tone={r.timing.stated ? "green" : "amber"}>
              {r.timing.stated ? r.timing.note : "No timing rule found"}
            </Status>
          </div>

          {r.missing.length > 0 && (
            <>
              <h3>Missing</h3>
              <ul className="small">{r.missing.map((m, i) => <li key={i}>{m}</li>)}</ul>
            </>
          )}
          {r.ambiguous.length > 0 && (
            <>
              <h3>Ambiguous (stated more than one way)</h3>
              <ul className="small">{r.ambiguous.map((a, i) => <li key={i}>{a}</li>)}</ul>
            </>
          )}

          <h3>Extracted text</h3>
          {/* Shown as plain text only — never rendered as HTML, never run as instructions. */}
          <pre className="import-text" style={{ whiteSpace: "pre-wrap", maxHeight: "18rem", overflow: "auto" }}>
            {upload!.text}
          </pre>

          <div className="email-actions">
            <button type="button" className="primary" disabled={busy || selected}
                    onClick={() => setSelectedHash(upload!.review.content_hash)}>
              <Check size={15} aria-hidden="true" />{" "}
              {selected ? `Selected version ${r.content_hash.slice(0, 8)}` : `Select this version (${r.content_hash.slice(0, 8)})`}
            </button>
          </div>
        </Card>
      )}

      {selected && (
        <Card title="Preview a candidate from this version" icon={BookOpen}>
          <p className="small muted">
            Renders follow-up 1 from the selected playbook, using the existing drafting checks. If the file
            changes, its version hash changes and you must review and select it again before previewing.
          </p>
          <div className="import-controls">
            <label className="small">
              Recipient first name{" "}
              <input value={firstName} onChange={(e) => setFirstName(e.target.value)} placeholder="there" />
            </label>
            <button type="button" className="primary" disabled={busy} onClick={runPreview}>
              Preview follow-up 1
            </button>
          </div>
          {candidate && candidate.body && (
            <pre className="import-text" style={{ whiteSpace: "pre-wrap" }}>{candidate.body}</pre>
          )}
          {candidate && !candidate.body && (
            <div className="callout amber" role="alert">
              <div className="callout-text">
                This version cannot produce a follow-up yet:
                <ul className="small">{candidate.problems.map((p, i) => <li key={i}>{p}</li>)}</ul>
              </div>
            </div>
          )}
        </Card>
      )}
    </>
  );
}
