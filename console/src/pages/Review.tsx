import { Check, Lock, RotateCw, TextQuote, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import {
  LoadError,
  ReviewStale,
  ReviewStatusUnavailable,
  loadReview,
  recordReview,
  type ReviewView,
} from "../api";
import { Card, Chip, ExternalLink, PageHead, Status, type Tone } from "../components";
import { safeHref } from "../format";

type Loader = (leadId: string) => Promise<ReviewView>;
type Recorder = (
  leadId: string,
  decision: "confirm" | "reject",
  fingerprint: string,
) => Promise<ReviewView>;

function stateOf(review: ReviewView["review"]): { tone: Tone; text: string } {
  if (review.decision === null) return { tone: "amber", text: "Awaiting your review" };
  if (!review.current)
    return { tone: "amber", text: "A previous review no longer matches this candidate — review it again" };
  const who = review.reviewer ? ` by ${review.reviewer}` : "";
  if (review.decision === "confirmed") return { tone: "green", text: `Confirmed${who}` };
  return { tone: "red", text: `Rejected${who}` };
}

/** One candidate email beside its cited evidence, for the founder to confirm or reject. Confirming
 *  is a human judgment, not proof; it neither sends nor drafts. An edit since it was shown is
 *  refused (the candidate must be reviewed again). Loading and recording are injectable for tests. */
export function Review({
  leadId,
  from,
  load = loadReview,
  record = recordReview,
}: {
  leadId: string;
  from: string;
  load?: Loader;
  record?: Recorder;
}) {
  const [view, setView] = useState<ReviewView | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  // The save succeeded but its resulting status could not be read: the shown decision is no longer
  // known, so no stale decision may be displayed and no further action is allowed until a reload.
  const [statusUnavailable, setStatusUnavailable] = useState(false);

  const fetch = useCallback(() => {
    load(leadId).then(
      (v) => {
        setView(v);
        setError("");
        setStatusUnavailable(false);  // a successful read re-establishes the current decision
      },
      (e: unknown) => setError(e instanceof LoadError ? e.message : "The candidate could not be loaded."),
    );
  }, [leadId, load]);

  useEffect(() => {
    fetch();
  }, [fetch]);

  const act = useCallback(
    (decision: "confirm" | "reject") => {
      if (!view || statusUnavailable) return;
      setBusy(true);
      record(leadId, decision, view.fingerprint).then(
        (v) => {
          setView(v);
          setError("");
          setBusy(false);
        },
        (e: unknown) => {
          setBusy(false);
          setError(e instanceof Error ? e.message : "The review could not be recorded.");
          if (e instanceof ReviewStatusUnavailable) {
            // Saved, but the current status is unknown. Do NOT keep showing the old decision, and
            // block further actions until a successful reload establishes the current one.
            setStatusUnavailable(true);
          } else if (e instanceof ReviewStale) {
            // The candidate changed; reload it so it can be reviewed afresh, message kept.
            load(leadId).then((v) => setView(v), () => {});
          }
        },
      );
    },
    [view, statusUnavailable, leadId, record, load],
  );

  if (!view) {
    return error ? (
      <Card title="This candidate cannot be reviewed">
        <p>{error}</p>
      </Card>
    ) : (
      <p className="muted loading" role="status">
        Loading the candidate…
      </p>
    );
  }

  const state = statusUnavailable
    ? { tone: "amber" as Tone, text: "Current status unavailable" }
    : stateOf(view.review);
  const quoteHref = safeHref(view.evidence?.url ?? "");
  return (
    <>
      <PageHead title="Review this candidate" sub="Read the email and its cited evidence, then confirm or reject.">
        <Chip tone={state.tone}>{state.text}</Chip>
      </PageHead>

      {error && (
        <div className="callout amber" role="alert">
          <div className="callout-text">{error}</div>
        </div>
      )}

      <div className="grid-2">
        <article className="email" aria-label={`Candidate to ${view.to}`}>
          <div className="email-top">
            <Status tone={state.tone}>{state.text}</Status>
          </div>
          <dl className="email-meta">
            <dt>From</dt>
            <dd>{from || "-"}</dd>
            <dt>To</dt>
            <dd>{view.to}</dd>
            <dt>Subject</dt>
            <dd className="subject">{view.subject || "-"}</dd>
          </dl>
          <div className="email-body">{view.body}</div>
        </article>

        <Card title="Cited evidence">
          {view.evidence ? (
            <figure className="source-quote">
              <TextQuote size={16} aria-hidden="true" />
              <div>
                <blockquote>“{view.evidence.quote}”</blockquote>
                <figcaption>
                  {quoteHref ? <ExternalLink href={quoteHref}>See the page</ExternalLink> : view.evidence.url}
                </figcaption>
              </div>
            </figure>
          ) : (
            <p className="muted">No cited quote for this candidate.</p>
          )}
          <h3>The claims to check against it</h3>
          <ul className="mini-list">
            {view.claims.map((claim, index) => (
              <li key={index}>
                <Chip tone="gray">{claim.kind}</Chip>
                <span>{claim.text}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>

      <Card title="Your judgment">
        <p className="muted small">{view.note}</p>
        {statusUnavailable && (
          <p className="muted small" role="status">
            The review was saved, but its current status could not be loaded. Reviewing is paused
            until you reload and the current decision is known again.
          </p>
        )}
        <div className="email-actions">
          <button type="button" className="primary" disabled={busy || statusUnavailable}
                  onClick={() => act("confirm")}>
            <Check size={15} aria-hidden="true" /> Confirm: the evidence supports these claims
          </button>
          <button type="button" className="secondary" disabled={busy || statusUnavailable}
                  onClick={() => act("reject")}>
            <X size={15} aria-hidden="true" /> Reject
          </button>
          {statusUnavailable && (
            <button type="button" className="secondary" onClick={fetch}>
              <RotateCw size={15} aria-hidden="true" /> Reload
            </button>
          )}
          <p className="muted small">
            <Lock size={13} aria-hidden="true" /> Confirming is your judgment, not proof the claims are true. It does
            not send or draft anything; sending and drafting stay disabled.
          </p>
        </div>
      </Card>
    </>
  );
}
