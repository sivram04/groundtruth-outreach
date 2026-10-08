import { Mail, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { CallError, prepareDraft, sendDraft, sendEditedDraft, type SendResult } from "../api";
import { Card } from "../components";
import type { Draft, Lead } from "../types";

/** The founder's ONE place to send: see the first draft written for them, edit it freely, then
 *  Approve and send. What leaves is exactly what is in the boxes — the server only ever adds back the
 *  opt-out line and keeps the no-spam / at-most-once guards. Composing (to pre-fill) and the two send
 *  paths are injectable for tests.
 *
 *  Three states: already sent (just reports it); a Gmail draft already created (send it as it is —
 *  editing would need it recreated, so that is the fallback path); otherwise the editable draft. */
export function ComposeAndSend({
  lead,
  draft,
  onChanged,
  compose = prepareDraft,
  sendEdited = sendEditedDraft,
  sendCreated = sendDraft,
}: {
  lead: Lead;
  draft?: Draft;
  onChanged?: () => void;
  compose?: typeof prepareDraft;
  sendEdited?: typeof sendEditedDraft;
  sendCreated?: typeof sendDraft;
}) {
  const alreadySent = Boolean(lead.cells["Sent at"]);
  const created = lead.gmail_drafts?.find((d) => d.status === "CREATED");
  const hasEmail = Boolean(lead.email && lead.email.trim());
  const [subject, setSubject] = useState(draft?.subject ?? "");
  const [body, setBody] = useState(draft?.body ?? "");
  const [touched, setTouched] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [done, setDone] = useState<SendResult | null>(null);

  // Pre-fill from a freshly composed draft, but never overwrite the founder's own edits.
  useEffect(() => {
    if (touched) return;
    setSubject(draft?.subject ?? "");
    setBody(draft?.body ?? "");
  }, [draft?.subject, draft?.body, touched]);

  if (alreadySent || done) {
    return (
      <Card title="Approve and send" icon={Send}>
        <p className="good">
          Sent{lead.email ? ` to ${lead.email}` : ""}
          {alreadySent && lead.cells["Sent at"] ? ` (${lead.cells["Sent at"]})` : ""}.
        </p>
        {done && !done.recorded && (
          <p className="callout amber">
            The email was sent, but recording it did not confirm. Reload before sending anything else.
          </p>
        )}
      </Card>
    );
  }

  async function writeFirst() {
    setBusy("compose");
    setError("");
    try {
      await compose(lead.id);
      onChanged?.();
    } catch (e) {
      setError(e instanceof CallError ? e.message : "The draft could not be written.");
    } finally {
      setBusy("");
    }
  }

  async function run(send: () => Promise<SendResult>) {
    setBusy("send");
    setError("");
    try {
      const result = await send();
      setDone(result);
      setConfirming(false);
      onChanged?.();
    } catch (e) {
      setError(e instanceof CallError ? e.message : "The email could not be sent.");
      setConfirming(false);
    } finally {
      setBusy("");
    }
  }

  // A Gmail draft already exists: send it as it is. (The editable path is used before any draft is
  // created; once one exists, editing would require recreating it.)
  if (created) {
    return (
      <Card title="Approve and send" icon={Send}>
        <p>
          A draft is ready in Gmail for <strong>{lead.email}</strong>. One click sends it, and a second click can
          never send it twice.
        </p>
        {error && <p className="callout amber">{error}</p>}
        {confirming ? (
          <div className="email-actions">
            <button type="button" className="primary" disabled={busy !== ""} onClick={() => run(() => sendCreated(lead.id))}>
              {busy === "send" ? "Sending…" : `Yes, send to ${lead.email}`}
            </button>
            <button type="button" className="secondary" disabled={busy !== ""} onClick={() => setConfirming(false)}>
              Cancel
            </button>
          </div>
        ) : (
          <button type="button" className="primary" onClick={() => setConfirming(true)}>
            <Send size={15} aria-hidden="true" /> Approve and send
          </button>
        )}
      </Card>
    );
  }

  // No usable address: there is nothing to send, so never offer the send. Say why, and what to do,
  // rather than show "Sending to —" with a live button that the server would only reject.
  if (!hasEmail) {
    return (
      <Card title="Write and send" icon={Mail}>
        <p className="muted">
          {lead.channel === "CALL"
            ? "This lead has a phone number but no email address, so there is nothing to send here. Log the call instead."
            : "No email address is on file for this lead yet, so nothing can be sent. Find a contact first, then a draft can be written and sent."}
        </p>
      </Card>
    );
  }

  const ready = subject.trim() !== "" && body.trim() !== "";
  return (
    <Card title="Write and send" icon={Mail}>
      <p className="muted small">
        A first draft is written for you from your handbook and the company's own site. Edit anything — what you
        send is exactly what's in these boxes.
      </p>
      {!draft && !touched && (
        <div className="email-actions">
          <button type="button" className="secondary" disabled={busy !== ""} onClick={writeFirst}>
            {busy === "compose" ? "Writing…" : "Write a first draft for me"}
          </button>
        </div>
      )}
      <label className="compose-field">
        <span className="field-label">Subject</span>
        <input
          type="text"
          value={subject}
          onChange={(e) => {
            setTouched(true);
            setSubject(e.target.value);
          }}
        />
      </label>
      <label className="compose-field">
        <span className="field-label">Message</span>
        <textarea
          rows={14}
          value={body}
          onChange={(e) => {
            setTouched(true);
            setBody(e.target.value);
          }}
        />
      </label>
      <p className="muted small">
        Sending to <strong>{lead.email || "—"}</strong>. The opt-out line is always kept.
      </p>
      {error && <p className="callout amber">{error}</p>}
      {confirming ? (
        <div className="email-actions">
          <button type="button" className="primary" disabled={busy !== "" || !ready} onClick={() => run(() => sendEdited(lead.id, subject, body))}>
            {busy === "send" ? "Sending…" : `Yes, send to ${lead.email}`}
          </button>
          <button type="button" className="secondary" disabled={busy !== ""} onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <button type="button" className="primary" disabled={!ready} onClick={() => setConfirming(true)}>
          <Send size={15} aria-hidden="true" /> Approve and send
        </button>
      )}
    </Card>
  );
}
