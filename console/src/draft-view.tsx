import { Lock, PenLine, Send, TextQuote, X } from "lucide-react";
import { useEffect, useRef } from "react";
import { ExternalLink, Status, draftTone } from "./components";
import { safeHref } from "./format";
import type { Draft } from "./types";

/** One draft as an email: who from and to, the subject, the words, the quote it opens with, and
 *  what it is waiting for. Editing and Approve arrive in the next step, and say so. */
export function DraftPreview({ draft, from }: { draft: Draft; from: string }) {
  const quoteHref = safeHref(draft.quote_href);
  return (
    <article className="email" aria-label={`Draft to ${draft.company}`}>
      <div className="email-top">
        <Status tone={draftTone(draft.status)}>{draft.status_label}</Status>
        {draft.prepared_at && <span className="muted small">Written {draft.prepared_at}</span>}
      </div>
      <dl className="email-meta">
        <dt>From</dt>
        <dd>{from || "-"}</dd>
        <dt>To</dt>
        <dd>
          {draft.contact && `${draft.contact} · `}
          {draft.to}
        </dd>
        <dt>Subject</dt>
        <dd className="subject">{draft.subject || "-"}</dd>
      </dl>
      {draft.body ? (
        <div className="email-body">{draft.body}</div>
      ) : (
        <p className="email-body empty">No words to show: this draft is held.</p>
      )}
      {draft.why.length > 0 && (
        <div className="why">
          <h3>{draft.status === "HELD" ? "Why it is held" : "What it waits for"}</h3>
          <ul>
            {draft.why.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        </div>
      )}
      {draft.quote && (
        <figure className="source-quote">
          <TextQuote size={16} aria-hidden="true" />
          <div>
            <blockquote>“{draft.quote}”</blockquote>
            <figcaption>
              The opening is written only from this line of their own site.{" "}
              {quoteHref ? <ExternalLink href={quoteHref}>See the page</ExternalLink> : draft.quote_page}
            </figcaption>
          </div>
        </figure>
      )}
      <div className="email-actions">
        <button type="button" className="secondary" disabled>
          <PenLine size={15} aria-hidden="true" /> Edit
        </button>
        <button type="button" className="primary" disabled>
          <Send size={15} aria-hidden="true" /> Approve and send
        </button>
        <p className="muted small">
          <Lock size={13} aria-hidden="true" /> Editing, and sending on approval, come in the next step.
        </p>
      </div>
    </article>
  );
}

/** A draft opened over the page. Escape, the close button or the shade around it close it. */
export function DraftDrawer({ draft, from, onClose }: { draft: Draft; from: string; onClose: () => void }) {
  const close = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const before = document.activeElement as HTMLElement | null;
    close.current?.focus();
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
      before?.focus?.();
    };
  }, [onClose]);
  return (
    <div className="shade" onClick={onClose}>
      <div
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`Draft to ${draft.company}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="drawer-head">
          <h2>{draft.company}</h2>
          <button type="button" className="icon-button" onClick={onClose} ref={close} aria-label="Close">
            <X size={18} aria-hidden="true" />
          </button>
        </div>
        <DraftPreview draft={draft} from={from} />
      </div>
    </div>
  );
}
