import { CalendarCheck, Reply, Trash2 } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { CallError, loadReplyCandidate } from "../api";
import { Card, ExternalLink } from "../components";
import type { ReplyCandidateResult } from "../types";

/** Show the reply-draft candidate for a lead that wrote back, beside its evidence, so the founder can read,
 *  edit (the fields are editable to copy from) or discard it. Nothing here sends, drafts to Gmail or
 *  persists: it is a candidate for review only, and it never states what the lead's reply said. `load` is
 *  injectable for tests. */
export function ReplyCandidate({
  leadId,
  reloadKey = "",
  load = loadReplyCandidate,
}: {
  leadId: string;
  /** Changes whenever this lead's state changes (a new event, a call stop), so the candidate is re-fetched
   *  and a stale editable draft is withdrawn or replaced after a parent refresh. */
  reloadKey?: string;
  load?: typeof loadReplyCandidate;
}) {
  const [result, setResult] = useState<ReplyCandidateResult | null>(null);
  const [error, setError] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [discarded, setDiscarded] = useState(false);
  // The pristine basis of the last fetched candidate; a re-fetch with the same basis keeps the founder's
  // edits, a different one adopts the new candidate (edits are not kept under a changed basis).
  const serverSig = useRef("");

  useEffect(() => {
    let live = true;
    setError("");
    load(leadId).then(
      (r) => {
        if (!live) return;
        setResult(r);
        if (!r.candidate) {
          serverSig.current = "";
          setDiscarded(false);
          return;
        }
        const c = r.candidate;
        const sig = `${leadId}\n${c.subject}\n${c.body}\n${c.booking_link}\n${c.handbook_hash}\n${c.in_reply_to}\n${JSON.stringify(c.evidence)}`;
        if (sig !== serverSig.current) {
          serverSig.current = sig;
          setSubject(c.subject);
          setBody(c.body);
          setDiscarded(false);
        }
      },
      (e: unknown) => live && setError(e instanceof CallError ? e.message : "The candidate could not be loaded."),
    );
    return () => {
      live = false;
    };
  }, [leadId, reloadKey, load]);

  if (error) {
    return (
      <Card title="Reply draft" icon={Reply}>
        <div className="callout amber" role="alert">
          <div className="callout-text">{error}</div>
        </div>
      </Card>
    );
  }
  if (!result) return null; // still loading; the rest of the lead page is already shown

  // Not applicable (no reply yet, or no email): show nothing at all.
  if (!result.candidate && (result.reason === "no_reply" || result.reason === "no_email")) {
    return null;
  }

  if (!result.candidate) {
    const said =
      result.reason === "suppressed"
        ? "This lead has opted out, so no reply draft is offered."
        : result.reason === "call_stop"
          ? "A recorded call outcome stops contact for this lead, so no reply draft is offered."
          : "The reply draft is unavailable right now (the events tab, call log, suppression list or handbook could not be read). Reload to try again.";
    return (
      <Card title="Reply draft" icon={Reply}>
        <div className={`callout ${result.unavailable ? "amber" : "blue"}`} role="alert">
          <div className="callout-text">{said}</div>
        </div>
      </Card>
    );
  }

  if (discarded) {
    return (
      <Card title="Reply draft" icon={Reply}>
        <p className="muted small">Discarded. Reload the lead to see it again.</p>
      </Card>
    );
  }

  const cand = result.candidate;
  return (
    <Card title="Reply draft" icon={Reply}>
      <p className="small muted">
        A suggested reply to read, edit or copy into the thread after this lead wrote back. It is not sent and
        creates no Gmail draft, and it does not repeat what their reply said — read their message in Gmail.
      </p>
      <label className="block small muted" htmlFor="reply-subject">
        Subject
      </label>
      <input id="reply-subject" className="import-text" value={subject} onChange={(e) => setSubject(e.target.value)} />
      <label className="block small muted" htmlFor="reply-body">
        Message
      </label>
      <textarea id="reply-body" className="import-text" rows={12} value={body} onChange={(e) => setBody(e.target.value)} />
      <div className="email-actions">
        <button type="button" className="secondary" onClick={() => setDiscarded(true)}>
          <Trash2 size={15} aria-hidden="true" /> Discard
        </button>
      </div>

      <h3>What this is based on</h3>
      <dl className="facts">
        {cand.booking_link && (
          <>
            <dt>Booking link</dt>
            <dd>
              <CalendarCheck size={14} aria-hidden="true" /> <ExternalLink href={cand.booking_link}>{cand.booking_link}</ExternalLink>
            </dd>
          </>
        )}
        {cand.evidence && (
          <>
            <dt>Company evidence</dt>
            <dd>
              “{cand.evidence.quote}” <ExternalLink href={cand.evidence.url}>source</ExternalLink>
            </dd>
          </>
        )}
        {cand.handbook_name && (
          <>
            <dt>Handbook</dt>
            <dd>
              {cand.handbook_name}
              {cand.handbook_hash && ` (${cand.handbook_hash.slice(0, 8)})`}
            </dd>
          </>
        )}
      </dl>
    </Card>
  );
}
