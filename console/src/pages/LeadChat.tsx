import { Check, UserPlus, X } from "lucide-react";
import { useState } from "react";
import { CallError, applyLeadChange, interpretLeadChange } from "../api";
import { Card, Status } from "../components";
import type { LeadChatProposal } from "../types";

/** Manage leads by typing an instruction: add a lead, or update an existing one's system fields.
 *  Read → confirm → write, never before the founder confirms. The read step is read-only and never calls
 *  a model; the confirm re-validates server-side. An existing lead's founder columns stay protected.
 *  `interpret`/`apply` are injectable for tests. */
export function LeadChat({
  onChanged,
  interpret = interpretLeadChange,
  apply = applyLeadChange,
}: {
  onChanged: () => void;
  interpret?: typeof interpretLeadChange;
  apply?: typeof applyLeadChange;
}) {
  const [note, setNote] = useState("");
  const [proposal, setProposal] = useState<LeadChatProposal | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState("");

  function read() {
    if (busy || !note.trim()) return;
    setBusy(true);
    setError("");
    setSaved("");
    interpret(note).then(
      (p) => {
        setBusy(false);
        setProposal(p);
      },
      (e: unknown) => {
        setBusy(false);
        setError(e instanceof CallError ? e.message : "The instruction could not be read.");
      },
    );
  }

  function confirm(p: LeadChatProposal) {
    if (busy || p.status !== "ready" || !p.op || !p.fields) return;
    setBusy(true);
    setError("");
    apply({ op: p.op, lead_id: p.lead_id, fields: p.fields }).then(
      (result) => {
        setBusy(false);
        onChanged();
        setSaved(p.op === "add" ? `Added ${result.lead_id || "the lead"}.` : `Updated ${result.lead_id}.`);
        setProposal(null);
        setNote("");
      },
      (e: unknown) => {
        setBusy(false); // keep the proposal so the founder can retry or cancel
        setError(e instanceof CallError ? e.message : "The change could not be saved.");
      },
    );
  }

  return (
    <Card title="Add or update a lead by note" icon={UserPlus}>
      <p className="small muted">
        Type an instruction; I will show exactly what will change and you confirm before anything is written.
        Format: <code>add | Company: Acme | email: sam@acme.test | website: https://acme.test</code> — or{" "}
        <code>update A-0001 | fit: QUALIFIED | profile: READY</code>. A lead's own company, email and website
        are protected and are not changed by an update.
      </p>
      <textarea
        className="import-text"
        rows={2}
        value={note}
        placeholder="e.g. add | Company: Acme Electric | email: sam@acme.test | website: https://acme.test"
        onChange={(e) => {
          setNote(e.target.value);
          setProposal(null);
          setSaved("");
        }}
      />
      <div className="email-actions">
        <button type="button" className="primary" disabled={busy || !note.trim()} onClick={read}>
          {busy ? "Reading…" : "Read it"}
        </button>
      </div>

      {saved && <p className="small unstorable">{saved}</p>}

      {proposal?.status === "unclear" && (
        <p className="small">
          I could not read a field. Use <code>field: value</code> pairs separated by <code>|</code>, e.g.{" "}
          <code>add | Company: Acme | email: sam@acme.test</code>.
        </p>
      )}
      {proposal?.status === "need_more" && (
        <p className="small">
          {proposal.reason === "unstorable"
            ? `This sheet has no column for: ${(proposal.columns ?? []).join(", ")}.`
            : "To add a lead I need a company and at least one of email, phone or website."}
        </p>
      )}
      {proposal?.status === "bad_email" && (
        <p className="small">That email does not look valid: {proposal.value}. Nothing was changed.</p>
      )}
      {proposal?.status === "no_lead" && (
        <p className="small">There is no lead {proposal.lead_id}. Check the Lead ID.</p>
      )}
      {proposal?.status === "protected" && (
        <div className="callout amber" role="alert">
          <div className="callout-text">
            A lead's own columns are protected and not changed here:{" "}
            <strong>{(proposal.columns ?? []).join(", ")}</strong>. You can set its system fields (fit, profile,
            email check, evidence) by note, but edit its company/email/website in the Sheet.
          </div>
        </div>
      )}

      {proposal?.status === "ready" && proposal.fields && (
        <div className="call-task">
          <div className="chips">
            <Status tone={proposal.op === "add" ? "green" : "amber"}>
              {proposal.op === "add" ? "Add a new lead" : `Update ${proposal.lead_id}`}
            </Status>
            {proposal.op === "update" && proposal.company && <span className="strong">{proposal.company}</span>}
          </div>
          <dl className="facts">
            {Object.entries(proposal.fields).map(([field, value]) => (
              <div className="pair" key={field}>
                <dt>{field}</dt>
                <dd>{value}</dd>
              </div>
            ))}
          </dl>
          <div className="email-actions">
            <button type="button" className="primary" disabled={busy} onClick={() => confirm(proposal)}>
              <Check size={15} aria-hidden="true" /> Confirm and save
            </button>
            <button type="button" className="secondary" disabled={busy} onClick={() => { setProposal(null); setError(""); }}>
              <X size={15} aria-hidden="true" /> Cancel
            </button>
          </div>
        </div>
      )}

      {error && (
        <div className="callout amber" role="alert">
          <div className="callout-text">{error}</div>
          {proposal?.status === "ready" && (
            <button type="button" className="secondary" disabled={busy} onClick={() => confirm(proposal)}>
              Try again
            </button>
          )}
        </div>
      )}
    </Card>
  );
}
