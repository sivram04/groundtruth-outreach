import type { ReactNode } from "react";
import { NAME } from "./brand";
import type { Page } from "./router";
import type { Approvals } from "./types";

const TABS: [Page, string, string][] = [
  ["dashboard", "#/", "Dashboard"],
  ["drafts", "#/drafts", "Drafts"],
  ["leads", "#/leads", "Leads"],
  ["sources", "#/sources", "Sources"],
];

export function Layout(props: {
  page: Page;
  signedInAs: string;
  readAt: string;
  refreshing: boolean;
  onRefresh: () => void;
  children: ReactNode;
}) {
  const active = props.page === "lead" ? "leads" : props.page;
  return (
    <>
      <header className="top">
        <div className="bar">
          <a className="brand" href="#/">
            {NAME}
          </a>
          <nav aria-label="Pages">
            {TABS.map(([page, link, label]) => (
              <a
                key={page}
                href={link}
                className={active === page ? "on" : undefined}
                aria-current={active === page ? "page" : undefined}
              >
                {label}
              </a>
            ))}
          </nav>
          <div className="who">
            {props.signedInAs && <span className="small muted">{props.signedInAs}</span>}
            <button type="button" className="quiet" onClick={props.onRefresh} disabled={props.refreshing}>
              {props.refreshing ? "Reading…" : "Refresh"}
            </button>
          </div>
        </div>
      </header>
      <main>{props.children}</main>
      <footer>
        Read-only for now: nothing here changes the Sheet or Gmail.
        {props.readAt && ` Read from the Sheet at ${props.readAt}.`}
      </footer>
    </>
  );
}

export function Pill(props: { tone: string; children: ReactNode }) {
  return <span className={`pill ${props.tone}`}>{props.children}</span>;
}

export function Card(props: { title?: string; children: ReactNode; className?: string }) {
  return (
    <section className={`card ${props.className ?? ""}`.trim()}>
      {props.title && <h2>{props.title}</h2>}
      {props.children}
    </section>
  );
}

export function Warnings(props: { warnings: string[] }) {
  return (
    <>
      {props.warnings.map((warning) => (
        <p key={warning} className="warn" role="alert">
          {warning}
        </p>
      ))}
    </>
  );
}

export function ExternalLink(props: { href: string; children: ReactNode }) {
  return (
    <a href={props.href} target="_blank" rel="noopener noreferrer">
      {props.children}
    </a>
  );
}

/** What the drafting settings say drafting is waiting for. */
export function DraftingSettings(props: { approvals: Approvals | null; withSender?: boolean }) {
  const a = props.approvals;
  if (!a) {
    return <p className="warn">The console was given no drafting settings, so it cannot say what drafting waits for.</p>;
  }
  return (
    <dl className="facts">
      <dt>Offer wording</dt>
      <dd>
        {a.offer ? (
          <Pill tone="ok">Approved</Pill>
        ) : (
          <>
            <Pill tone="wait">Not approved</Pill> First drafts wait for your approval of the offer wording in the
            handbook.
          </>
        )}
      </dd>
      <dt>Follow-up wording</dt>
      <dd>
        {a.followups ? (
          <>
            <Pill tone="ok">Approved</Pill> for one version of the handbook: a change to the handbook needs a new
            approval.
          </>
        ) : (
          <>
            <Pill tone="wait">Not approved</Pill> Follow-up drafts wait for your approval of the handbook's follow-up
            wording.
          </>
        )}
      </dd>
      <dt>Tracking in new drafts</dt>
      <dd>{a.tracking ? "On" : "Off"}</dd>
      <dt>Drafts a day, at most</dt>
      <dd>{a.daily_cap ?? "not set"}</dd>
      {props.withSender && (
        <>
          <dt>Sends from</dt>
          <dd>{a.sender || "not set"}</dd>
        </>
      )}
    </dl>
  );
}
