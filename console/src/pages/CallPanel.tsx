import { Check, Phone, RotateCw, X } from "lucide-react";
import { useRef, useState } from "react";
import { CallError, actOnCallTask, recordCallOutcome } from "../api";
import { Card, Status } from "../components";
import type { CallHistoryItem, CallTask } from "../types";

/** A fresh identity for one logical call submission. */
function newSubmissionId(): string {
  const c = globalThis.crypto as Crypto | undefined;
  if (c?.randomUUID) return c.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

const OUTCOMES: [string, string][] = [
  ["NO_ANSWER", "No answer"],
  ["INTERESTED", "Interested"],
  ["NOT_INTERESTED", "Not interested"],
  ["CALLBACK", "Callback requested"],
  ["WRONG_NUMBER", "Wrong number"],
  ["DO_NOT_CONTACT", "Do not contact"],
];

/** Turn a datetime-local value ("2026-10-01T18:00", in the founder's own timezone) into an ISO string
 *  with its offset, so the server stores the real instant, not a naive time read as UTC. */
function toIso(local: string): string | undefined {
  if (!local) return undefined;
  const when = new Date(local);
  return Number.isNaN(when.getTime()) ? undefined : when.toISOString();
}

/** Log a call and manage the resulting call task, from the lead page. Records nothing until the founder
 *  acts; sends and drafts nothing. Record/act are injectable for tests. */
export function CallPanel({
  leadId,
  phone,
  task,
  history = [],
  effectSaid = "",
  onChanged,
  record = recordCallOutcome,
  act = actOnCallTask,
}: {
  leadId: string;
  phone: string;
  task: CallTask | null;
  history?: CallHistoryItem[];
  effectSaid?: string;
  onChanged: () => void;
  record?: typeof recordCallOutcome;
  act?: typeof actOnCallTask;
}) {
  const [outcome, setOutcome] = useState("NO_ANSWER");
  const [note, setNote] = useState("");
  const [callbackAt, setCallbackAt] = useState("");
  const [snoozeAt, setSnoozeAt] = useState("");
  const [showSnooze, setShowSnooze] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  // A partial success: the call was recorded but something else (its suppression entry) was not.
  const [warning, setWarning] = useState("");
  // One logical submission's identity. It survives a retry (so a lost response after a successful write,
  // or a partial success, makes no duplicate call) and is cleared on a clean success or whenever the form
  // is edited (so a genuinely new call is recorded). The UI omits the call time, so this - not a server
  // timestamp - is the identity.
  const submissionId = useRef("");

  function editField<T>(set: (v: T) => void) {
    return (v: T) => {
      submissionId.current = "";
      setWarning("");
      set(v);
    };
  }

  function save() {
    if (busy) return;
    if (outcome === "CALLBACK" && !callbackAt) {
      setError("A callback needs an explicit date and time.");
      return;
    }
    if (!submissionId.current) submissionId.current = newSubmissionId();
    setBusy(true);
    setError("");
    record(leadId, {
      outcome, note, submission_id: submissionId.current,
      callback_at: outcome === "CALLBACK" ? toIso(callbackAt) : undefined,
    }).then(
      (result) => {
        setBusy(false);
        onChanged();  // the call itself was recorded, so refresh the task/history either way
        if (result?.suppression_written === false || result?.warning) {
          // A partial success. Keep the submission identity and the form so a retry re-attempts the rest
          // WITHOUT recording a second call (the same submission id is idempotent), and tell the founder.
          setWarning(
            result.warning ||
              "The call was recorded, but its suppression entry was not written. The email suppression list may be incomplete until you retry.",
          );
          return;
        }
        setWarning("");
        submissionId.current = "";
        setNote("");
        setCallbackAt("");
      },
      (e: unknown) => {
        setBusy(false);  // keep submissionId so the next click retries the same submission
        setError(e instanceof CallError ? e.message : "The call could not be recorded.");
      },
    );
  }

  function doAction(action: string, snooze_to?: string) {
    if (busy || !task) return;
    setBusy(true);
    setError("");
    act(leadId, { action, snooze_to, task_id: task.id }).then(
      () => {
        setBusy(false);
        setShowSnooze(false);
        setSnoozeAt("");
        onChanged();
      },
      (e: unknown) => {
        setBusy(false);
        setError(e instanceof CallError ? e.message : "The task could not be updated.");
      },
    );
  }

  return (
    <Card title="Calls" icon={Phone}>
      {task && task.status === "scheduled" ? (
        <div className="call-task">
          <div className="chips">
            <Status tone={task.overdue ? "red" : "amber"}>{task.overdue ? "Overdue" : "Call due"}</Status>
            <span className="strong">{task.due_text}</span>
            {task.snoozed && <span className="small muted">(snoozed)</span>}
          </div>
          <p className="small">
            {task.why}
            {task.note && ` — ${task.note}`}
          </p>
          <div className="email-actions">
            <button type="button" className="primary" disabled={busy} onClick={() => doAction("COMPLETE")}>
              <Check size={15} aria-hidden="true" /> Complete
            </button>
            <button type="button" className="secondary" disabled={busy} onClick={() => setShowSnooze((s) => !s)}>
              <RotateCw size={15} aria-hidden="true" /> Snooze
            </button>
            <button type="button" className="secondary" disabled={busy} onClick={() => doAction("CANCEL")}>
              <X size={15} aria-hidden="true" /> Cancel
            </button>
          </div>
          {showSnooze && (
            <div className="import-controls">
              <label className="small">
                Snooze until{" "}
                <input type="datetime-local" value={snoozeAt} onChange={(e) => setSnoozeAt(e.target.value)} />
              </label>
              <button type="button" className="primary" disabled={busy || !snoozeAt}
                      onClick={() => doAction("SNOOZE", toIso(snoozeAt))}>
                Save snooze
              </button>
            </div>
          )}
        </div>
      ) : (
        <p className="muted small">No call scheduled.{phone ? ` Phone: ${phone}` : " No phone on file."}</p>
      )}

      {effectSaid && <p className="small unstorable">{effectSaid}</p>}

      <h3>Log a call</h3>
      <div className="import-controls">
        <label className="small">
          Outcome{" "}
          <select value={outcome} onChange={(e) => editField(setOutcome)(e.target.value)}>
            {OUTCOMES.map(([value, label]) => (
              <option key={value} value={value}>{label}</option>
            ))}
          </select>
        </label>
        {outcome === "CALLBACK" && (
          <label className="small">
            Callback at{" "}
            <input type="datetime-local" value={callbackAt} onChange={(e) => editField(setCallbackAt)(e.target.value)} />
          </label>
        )}
      </div>
      <label className="block small muted" htmlFor="call-note">Note</label>
      <textarea id="call-note" className="import-text" rows={2} value={note}
                placeholder="e.g. Called today — no answer" onChange={(e) => editField(setNote)(e.target.value)} />
      <div className="email-actions">
        <button type="button" className="primary" disabled={busy} onClick={save}>
          <Phone size={15} aria-hidden="true" /> {busy ? "Saving…" : "Save call"}
        </button>
      </div>

      {error && (
        <div className="callout amber" role="alert">
          <div className="callout-text">{error}</div>
        </div>
      )}

      {warning && (
        <div className="callout amber" role="alert">
          <div className="callout-text">
            <strong>The call was saved. One step did not finish.</strong>
            <span className="block small">{warning}</span>
          </div>
          <button type="button" className="secondary" disabled={busy} onClick={save}>
            <RotateCw size={15} aria-hidden="true" /> Retry the rest
          </button>
        </div>
      )}

      {history.length > 0 && (
        <>
          <h3>Call history</h3>
          <ol className="history">
            {history.map((item, index) => (
              <li key={index}>
                <span className="history-when">{item.when}</span>
                <span>
                  <strong>{item.what}</strong>
                  {item.note && <span className="block small">{item.note}</span>}
                </span>
              </li>
            ))}
          </ol>
        </>
      )}
    </Card>
  );
}
