import { Check, Phone, RotateCw, X } from "lucide-react";
import { useState } from "react";
import { CallError, actOnCallTask } from "../api";
import { Avatar, Card, Status } from "../components";
import { leadHref } from "../router";
import type { CallQueueItem } from "../types";

/** Turn a datetime-local value into an ISO instant with its offset (see CallPanel). */
function toIso(local: string): string | undefined {
  if (!local) return undefined;
  const when = new Date(local);
  return Number.isNaN(when.getTime()) ? undefined : when.toISOString();
}

/** One call in the queue, with the actions bound to its exact task id. */
function QueueItem({
  item,
  onChanged,
  act,
}: {
  item: CallQueueItem;
  onChanged: () => void;
  act: typeof actOnCallTask;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [showSnooze, setShowSnooze] = useState(false);
  const [snoozeAt, setSnoozeAt] = useState("");

  function run(action: string, snooze_to?: string) {
    if (busy) return;
    setBusy(true);
    setError("");
    act(item.lead_id, { action, task_id: item.id, snooze_to }).then(
      () => {
        setBusy(false);
        setShowSnooze(false);
        setSnoozeAt("");
        onChanged(); // the task left the open queue (done/cancelled) or moved (snoozed); re-read
      },
      (e: unknown) => {
        setBusy(false);
        // A stale task (409 - a newer outcome replaced it) or any other refusal: keep the explanation on
        // screen and offer an explicit Reload, so the next action targets the refreshed task id rather
        // than the stale one this item was rendered with.
        setError(e instanceof CallError ? e.message : "The task could not be updated.");
      },
    );
  }

  return (
    <li>
      <Avatar name={item.company || item.lead_id} />
      <div className="needs-main">
        <div className="needs-line">
          <a href={leadHref(item.lead_id)} className="strong">
            {item.company || item.lead_id}
          </a>
          <Status tone={item.overdue ? "red" : "amber"}>{item.overdue ? "Overdue" : "Due today"}</Status>
          <span className="strong">{item.due_text}</span>
        </div>
        <p className="small">
          {item.why}
          {item.note && ` — ${item.note}`}
        </p>
        <p className="small muted">
          {item.lead_id}
          {item.contact && ` · ${item.contact}`}
          {item.phone ? ` · ${item.phone}` : " · no phone on file"}
        </p>
        <div className="email-actions">
          <button type="button" className="primary" disabled={busy} onClick={() => run("COMPLETE")}>
            <Check size={15} aria-hidden="true" /> Complete
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => setShowSnooze((s) => !s)}>
            <RotateCw size={15} aria-hidden="true" /> Snooze
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => run("CANCEL")}>
            <X size={15} aria-hidden="true" /> Cancel
          </button>
        </div>
        {showSnooze && (
          <div className="import-controls">
            <label className="small">
              Snooze until{" "}
              <input type="datetime-local" value={snoozeAt} onChange={(e) => setSnoozeAt(e.target.value)} />
            </label>
            <button
              type="button"
              className="primary"
              disabled={busy || !snoozeAt}
              onClick={() => run("SNOOZE", toIso(snoozeAt))}
            >
              Save snooze
            </button>
          </div>
        )}
        {error && (
          <div className="callout amber" role="alert">
            <div className="callout-text">{error}</div>
            <button type="button" className="secondary" disabled={busy} onClick={onChanged}>
              <RotateCw size={15} aria-hidden="true" /> Reload the queue
            </button>
          </div>
        )}
      </div>
    </li>
  );
}

/** The dashboard call queue: overdue first, then due today, with upcoming kept separate. Shown only when
 *  the call-task flow is on. Reuses the existing task identity and Complete/Snooze/Cancel API. */
export function CallQueue({
  tasks,
  unreadable,
  onChanged,
  act = actOnCallTask,
}: {
  tasks: CallQueueItem[];
  unreadable?: boolean;
  onChanged: () => void;
  act?: typeof actOnCallTask;
}) {
  // The call log or the suppression list could not be read: an unavailable state, NEVER "no calls due"
  // (which would hide real calls, or wrongly include a lead who opted out). The founder is told to reload
  // rather than shown an empty, falsely-reassuring queue.
  if (unreadable) {
    return (
      <Card title="Calls to make">
        <div className="callout amber" role="alert">
          <div className="callout-text">
            The call log or the suppression list could not be read, so the call queue is unavailable right
            now. Reload to try again; do not assume there are no calls due.
          </div>
        </div>
      </Card>
    );
  }

  // Overdue first, then due today (both already overdue-first, due-date ordered by the server), with
  // upcoming calls listed separately so they do not crowd what is due now.
  const due = tasks.filter((t) => t.when === "OVERDUE" || t.when === "TODAY");
  const upcoming = tasks.filter((t) => t.when === "UPCOMING");
  const overdueCount = tasks.filter((t) => t.when === "OVERDUE").length;

  return (
    <Card
      title="Calls to make"
      icon={Phone}
      action={overdueCount > 0 ? <Status tone="red">{overdueCount} overdue</Status> : undefined}
    >
      {due.length === 0 ? (
        <p className="muted">No calls are due right now.</p>
      ) : (
        <ul className="needs">
          {due.map((item) => (
            <QueueItem key={item.id} item={item} onChanged={onChanged} act={act} />
          ))}
        </ul>
      )}
      {upcoming.length > 0 && (
        <details>
          <summary className="small">{upcoming.length} upcoming</summary>
          <ul className="timeline">
            {upcoming.map((item) => (
              <li key={item.id}>
                <span className="timeline-day">{item.due_text}</span>
                <span>
                  <a href={leadHref(item.lead_id)} className="strong">
                    {item.company || item.lead_id}
                  </a>
                  <span className="small muted block">
                    {item.why}
                    {item.note && ` — ${item.note}`}
                  </span>
                  <span className="small muted block">
                    {item.contact && `${item.contact} · `}
                    {item.phone ? item.phone : "no phone on file"}
                  </span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </Card>
  );
}
