import { Check, MessageSquare, Phone, X } from "lucide-react";
import { useState } from "react";
import { CallError, interpretCallNote, recordCallOutcome } from "../api";
import { Card, Status } from "../components";
import { leadHref } from "../router";
import type { CallProposal, CallProposalLead } from "../types";

const OUTCOME_LABELS: Record<string, string> = {
  NO_ANSWER: "No answer",
  INTERESTED: "Interested",
  NOT_INTERESTED: "Not interested",
  CALLBACK: "Callback requested",
  WRONG_NUMBER: "Wrong number",
  DO_NOT_CONTACT: "Do not contact",
};

function toIso(local: string): string | undefined {
  if (!local) return undefined;
  const when = new Date(local);
  return Number.isNaN(when.getTime()) ? undefined : when.toISOString();
}

/** Log a call by typing a short note. Read → confirm → write, never write before the founder confirms. The
 *  interpret step is read-only; the confirm reuses the ordinary call-outcome route (its submission identity,
 *  scheduling and STOP/HOLD and sticky do-not-contact rules). Separate from the general assistant, which
 *  stays read-only. `interpret`/`record` are injectable for tests. */
export function CallLogChat({
  onChanged,
  interpret = interpretCallNote,
  record = recordCallOutcome,
}: {
  onChanged: () => void;
  interpret?: typeof interpretCallNote;
  record?: typeof recordCallOutcome;
}) {
  const [note, setNote] = useState("");
  const [proposal, setProposal] = useState<CallProposal | null>(null);
  const [callbackAt, setCallbackAt] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [warning, setWarning] = useState("");
  const [saved, setSaved] = useState("");

  function read(refine: { lead_id?: string; callback_at?: string } = {}) {
    if (busy || !note.trim()) return;
    setBusy(true);
    setError("");
    setWarning("");
    setSaved("");
    interpret(note, refine).then(
      (p) => {
        setBusy(false);
        setProposal(p);
      },
      (e: unknown) => {
        setBusy(false);
        setError(e instanceof CallError ? e.message : "The note could not be read.");
      },
    );
  }

  function confirm(p: CallProposal) {
    if (busy || !p.lead || !p.outcome) return;
    setBusy(true);
    setError("");
    setWarning("");
    record(p.lead.lead_id, {
      outcome: p.outcome,
      note: p.note,
      called_at: p.called_at || undefined, // pin the call time so the saved due matches the preview
      callback_at: p.callback_at || undefined,
      submission_id: p.submission_id, // the proposal's own id: a retry after a lost response makes no duplicate
    }).then(
      (result) => {
        setBusy(false);
        onChanged(); // the call itself was recorded either way, so refresh the queue
        if (result?.suppression_written === false || result?.warning) {
          // A partial success (the call's stop was recorded but its Suppression entry was not). Keep the
          // proposal and its submission id so Retry re-attempts the suppression write without a second call.
          setWarning(
            result.warning ||
              "The call was recorded, but its suppression entry was not written. The email suppression list may be incomplete until you retry.",
          );
          return;
        }
        setSaved(`Saved for ${p.lead?.company || p.lead?.lead_id}.`);
        setProposal(null);
        setNote("");
        setCallbackAt("");
      },
      (e: unknown) => {
        setBusy(false); // keep the proposal so Confirm retries with the same submission id
        setError(e instanceof CallError ? e.message : "The call could not be recorded.");
      },
    );
  }

  function leadLine(lead: CallProposalLead) {
    return `${lead.lead_id}${lead.contact ? ` · ${lead.contact}` : ""} · ${lead.email || lead.phone || "no email or phone"}`;
  }

  return (
    <Card title="Log a call by note" icon={MessageSquare}>
      <p className="small muted">
        Type what happened; I will show the lead, the saved note and the next call date to confirm before
        anything is written. Nothing is sent and no email is drafted.
      </p>
      <textarea
        className="import-text"
        rows={2}
        value={note}
        placeholder="e.g. Called Dana at Bluebird today, no answer; remind me to call again."
        onChange={(e) => {
          setNote(e.target.value);
          setProposal(null); // a changed note needs a fresh read
          setSaved("");
        }}
      />
      <div className="email-actions">
        <button type="button" className="primary" disabled={busy || !note.trim()} onClick={() => read()}>
          {busy ? "Reading…" : "Read it"}
        </button>
      </div>

      {saved && <p className="small unstorable">{saved}</p>}

      {proposal?.status === "unclear_outcome" && (
        <p className="small">
          I could not tell the outcome. Mention no answer, interested, callback, not interested, wrong number
          or do not contact.
        </p>
      )}
      {proposal?.status === "no_lead" && (
        <p className="small">I could not find a matching lead. Include the company or the person's name.</p>
      )}

      {proposal?.status === "choose_lead" && (
        <div>
          <p className="small strong">Which lead did you mean?</p>
          <ul className="needs">
            {(proposal.leads ?? []).map((lead) => (
              <li key={lead.lead_id}>
                <div className="needs-main">
                  <div className="needs-line">
                    <a href={leadHref(lead.lead_id)} className="strong">
                      {lead.company || lead.lead_id}
                    </a>
                    <button type="button" className="secondary" disabled={busy}
                            onClick={() => read({ lead_id: lead.lead_id })}>
                      Use this one
                    </button>
                  </div>
                  <p className="small muted">{leadLine(lead)}</p>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}

      {proposal?.status === "need_time" && proposal.lead && (
        <div className="import-controls">
          <p className="small">
            A callback for <span className="strong">{proposal.lead.company || proposal.lead.lead_id}</span>{" "}
            needs an explicit date and time — I will not guess one from the note.
          </p>
          <label className="small">
            Callback at{" "}
            <input type="datetime-local" value={callbackAt} onChange={(e) => setCallbackAt(e.target.value)} />
          </label>
          <button type="button" className="primary" disabled={busy || !callbackAt}
                  onClick={() => read({ lead_id: proposal.lead?.lead_id, callback_at: toIso(callbackAt) })}>
            Use this time
          </button>
        </div>
      )}

      {proposal?.status === "ready" && proposal.lead && (
        <div className="call-task">
          <div className="chips">
            <Status tone={proposal.do_not_contact ? "red" : "amber"}>
              {OUTCOME_LABELS[proposal.outcome ?? ""] ?? proposal.outcome}
            </Status>
            {proposal.due_text && <span className="strong">{proposal.due_text}</span>}
          </div>
          <dl className="facts">
            <dt>Lead</dt>
            <dd>
              <a href={leadHref(proposal.lead.lead_id)} className="strong">
                {proposal.lead.company || proposal.lead.lead_id}
              </a>
              <span className="block small muted">{leadLine(proposal.lead)}</span>
            </dd>
            <dt>Note to save</dt>
            <dd>{proposal.note}</dd>
          </dl>
          {proposal.do_not_contact && (
            <div className="callout amber" role="alert">
              <div className="callout-text">
                This marks <strong>{proposal.lead.company || proposal.lead.lead_id}</strong> as do-not-contact
                — a permanent stop on outreach that a later call will not lift.
              </div>
            </div>
          )}
          <div className="email-actions">
            <button type="button" className="primary" disabled={busy} onClick={() => confirm(proposal)}>
              <Check size={15} aria-hidden="true" /> Confirm and save
            </button>
            <button type="button" className="secondary" disabled={busy}
                    onClick={() => { setProposal(null); setError(""); }}>
              <X size={15} aria-hidden="true" /> Cancel
            </button>
          </div>
        </div>
      )}

      {warning && proposal?.status === "ready" && (
        <div className="callout amber" role="alert">
          <div className="callout-text">
            <strong>The call was saved. One step did not finish.</strong>
            <span className="block small">{warning}</span>
          </div>
          <button type="button" className="secondary" disabled={busy} onClick={() => confirm(proposal)}>
            <Phone size={15} aria-hidden="true" /> Retry the suppression write
          </button>
        </div>
      )}

      {error && (
        <div className="callout amber" role="alert">
          <div className="callout-text">{error}</div>
          {proposal?.status === "ready" && (
            <button type="button" className="secondary" disabled={busy} onClick={() => confirm(proposal)}>
              <Phone size={15} aria-hidden="true" /> Try again
            </button>
          )}
        </div>
      )}
    </Card>
  );
}
