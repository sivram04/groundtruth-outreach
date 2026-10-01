import { Mail, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";
import { CallError, loadCallCandidate } from "../api";
import { Card, ExternalLink } from "../components";
import type { CallCandidateResult } from "../types";

/** Show the post-call email candidate for a lead beside its evidence, so the founder can read, edit (the
 *  fields are editable to copy from) or discard it. Nothing here sends, drafts to Gmail or persists: it is
 *  a candidate for review only. A HOLD still blocks the ordinary email sequence; this does not authorize it.
 *  `load` is injectable for tests. */
export function PostCallCandidate({
  leadId,
  reloadKey = "",
  load = loadCallCandidate,
}: {
  leadId: string;
  /** A value that changes whenever this lead's call state changes (a new outcome, a stop, a snooze), so the
   *  candidate is re-fetched and a stale editable draft is withdrawn or replaced after a parent refresh. */
  reloadKey?: string;
  load?: typeof loadCallCandidate;
}) {
  const [result, setResult] = useState<CallCandidateResult | null>(null);
  const [error, setError] = useState("");
  const [subject, setSubject] = useState("");
  const [body, setBody] = useState("");
  const [discarded, setDiscarded] = useState(false);

  useEffect(() => {
    let live = true;
    setResult(null);
    setError("");
    setDiscarded(false);
    load(leadId).then(
      (r) => {
        if (!live) return;
        setResult(r);
        if (r.candidate) {
          setSubject(r.candidate.subject);
          setBody(r.candidate.body);
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
      <Card title="Post-call email" icon={Mail}>
        <div className="callout amber" role="alert">
          <div className="callout-text">{error}</div>
        </div>
      </Card>
    );
  }
  if (!result) return null; // still loading; the rest of the lead page is already shown

  // Not applicable (a phone-only lead, or an outcome that warrants no outreach): show nothing at all.
  if (!result.candidate && (result.reason === "no_email" || result.reason === "outcome_not_eligible")) {
    return null;
  }

  if (!result.candidate) {
    const said =
      result.reason === "suppressed"
        ? "This lead has opted out, so no post-call email is offered."
        : "The post-call email is unavailable right now (the call log, suppression list or handbook could not be read). Reload to try again.";
    return (
      <Card title="Post-call email" icon={Mail}>
        <div className={`callout ${result.unavailable ? "amber" : "blue"}`} role="alert">
          <div className="callout-text">{said}</div>
        </div>
      </Card>
    );
  }

  if (discarded) {
    return (
      <Card title="Post-call email" icon={Mail}>
        <p className="muted small">Discarded. Reload the lead to see it again.</p>
      </Card>
    );
  }

  const cand = result.candidate;
  return (
    <Card title="Post-call email" icon={Mail}>
      <p className="small muted">
        A draft to read, edit or copy after your call. It is not sent and creates no Gmail draft; a hold still
        pauses the ordinary email sequence.
      </p>
      <label className="block small muted" htmlFor="pc-subject">
        Subject
      </label>
      <input id="pc-subject" className="import-text" value={subject} onChange={(e) => setSubject(e.target.value)} />
      <label className="block small muted" htmlFor="pc-body">
        Message
      </label>
      <textarea id="pc-body" className="import-text" rows={12} value={body} onChange={(e) => setBody(e.target.value)} />
      <div className="email-actions">
        <button type="button" className="secondary" onClick={() => setDiscarded(true)}>
          <Trash2 size={15} aria-hidden="true" /> Discard
        </button>
      </div>

      <h3>What this is based on</h3>
      <dl className="facts">
        <dt>Call outcome</dt>
        <dd>{cand.outcome.replace(/_/g, " ").toLowerCase()}</dd>
        {cand.callback_text && (
          <>
            <dt>Callback</dt>
            <dd>{cand.callback_text}</dd>
          </>
        )}
        {cand.note && (
          <>
            <dt>Your note</dt>
            <dd>{cand.note}</dd>
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
