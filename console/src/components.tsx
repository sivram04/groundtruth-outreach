import {
  ExternalLink as ExternalIcon,
  Info,
  PanelLeft,
  RefreshCw,
  TriangleAlert,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { NAME } from "./brand";
import type { Page } from "./router";
import type { Approvals } from "./types";

const NAV: [Page, string, string][] = [
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
  draftsWaiting: number;
  importEnabled?: boolean;
  playbookEnabled?: boolean;
  assistant: ReactNode;
  assistantShown: boolean;
  onAssistant: (shown: boolean) => void;
  onRefresh: () => void;
  children: ReactNode;
}) {
  const active = props.page === "lead" ? "leads" : props.page;
  const nav: [Page, string, string][] = [
    ...NAV,
    ...(props.importEnabled ? ([["import", "#/import", "Import"]] as [Page, string, string][]) : []),
    ...(props.playbookEnabled ? ([["playbook", "#/playbook", "Playbook"]] as [Page, string, string][]) : []),
  ];
  return (
    <div className={`shell${props.assistantShown ? " with-assistant" : ""}`}>
      {props.assistantShown && props.assistant}
      <div className="content">
        <header className="topbar">
          <a className="brand" href="#/">
            <span className="brand-mark" aria-hidden="true">
              {NAME.slice(0, 1)}
            </span>
            <span className="brand-name">{NAME.toLowerCase()}</span>
          </a>
          <button
            type="button"
            className="icon-button"
            onClick={() => props.onAssistant(!props.assistantShown)}
            aria-label={props.assistantShown ? "Hide the assistant" : "Ask the assistant"}
            aria-pressed={props.assistantShown}
          >
            <PanelLeft size={17} aria-hidden="true" />
          </button>
          <nav aria-label="Pages">
            {nav.map(([page, link, label]) => (
              <a
                key={page}
                href={link}
                className={active === page ? "on" : undefined}
                aria-current={active === page ? "page" : undefined}
              >
                {label}
                {page === "drafts" && props.draftsWaiting > 0 && (
                  <span className="count" aria-label={`${props.draftsWaiting} drafts`}>
                    {props.draftsWaiting}
                  </span>
                )}
              </a>
            ))}
          </nav>
          <div className="topbar-side">
            <span className="muted small read-at">{props.readAt && `Read ${props.readAt}`}</span>
            <button type="button" className="ghost" onClick={props.onRefresh} disabled={props.refreshing}>
              <RefreshCw size={14} aria-hidden="true" className={props.refreshing ? "spin" : undefined} />
              {props.refreshing ? "Reading…" : "Refresh"}
            </button>
            {props.signedInAs && (
              <span className="avatar small" title={props.signedInAs} aria-label={props.signedInAs}>
                {props.signedInAs.slice(0, 1).toUpperCase()}
              </span>
            )}
          </div>
        </header>
        <main>{props.children}</main>
        <footer>Nothing on these pages changes the Sheet or Gmail.</footer>
      </div>
    </div>
  );
}

/** A section: its name on the left, what can be done with it on the right. */
export function SectionHead(props: { title: string; children?: ReactNode }) {
  return (
    <div className="section-head">
      <h2>{props.title}</h2>
      {props.children && <div className="section-actions">{props.children}</div>}
    </div>
  );
}

/** The tabs over a table: each says how many rows it holds. */
export function CountTabs(props: {
  label: string;
  tabs: [string, string, number][];
  on: string;
  onPick: (key: string) => void;
}) {
  return (
    <div className="count-tabs" role="tablist" aria-label={props.label}>
      {props.tabs.map(([key, label, count]) => (
        <button
          key={key}
          type="button"
          role="tab"
          aria-selected={props.on === key}
          className={props.on === key ? "on" : undefined}
          onClick={() => props.onPick(key)}
        >
          {label}
          <span className="tab-count">{count}</span>
        </button>
      ))}
    </div>
  );
}

export function PageHead(props: { title: string; sub?: ReactNode; children?: ReactNode }) {
  return (
    <div className="page-head">
      <div>
        <h1>{props.title}</h1>
        {props.sub && <p className="muted">{props.sub}</p>}
      </div>
      {props.children && <div className="page-head-side">{props.children}</div>}
    </div>
  );
}

export type Tone = "green" | "amber" | "red" | "blue" | "gray" | "violet";

export function Chip(props: { tone: Tone; children: ReactNode }) {
  return <span className={`chip ${props.tone}`}>{props.children}</span>;
}

const LEAD_TONES: Record<string, Tone> = {
  "": "gray",
  DRAFTED: "blue",
  SENT: "blue",
  REPLIED: "green",
  OPTED_OUT: "red",
  BOUNCED: "red",
  REVIEW_NEEDED: "amber",
};

export function leadTone(status: string): Tone {
  return LEAD_TONES[status] ?? "gray";
}

const DRAFT_TONES: Record<string, Tone> = { READY: "green", WAITING: "amber", HELD: "red" };

export function draftTone(status: string): Tone {
  return DRAFT_TONES[status] ?? "gray";
}

/** A company's initials. One quiet shape, one colour: the status says what matters. */
export function Avatar(props: { name: string; size?: "small" | "large" }) {
  const words = props.name.replace(/<[^>]*>/g, " ").match(/[A-Za-z0-9]+/g) ?? [];
  const letters = (words.length > 1 ? (words[0]![0] ?? "") + (words[1]![0] ?? "") : (words[0] ?? "?").slice(0, 2))
    .toUpperCase();
  return (
    <span className={`avatar ${props.size ?? ""}`.trim()} aria-hidden="true">
      {letters}
    </span>
  );
}

/** A status: a small dot and its name, never a whole block of colour. */
export function Status(props: { tone: Tone; children: ReactNode }) {
  return (
    <span className={`status ${props.tone}`}>
      <span className="dot" aria-hidden="true" />
      {props.children}
    </span>
  );
}

export function Card(props: {
  title?: string;
  icon?: LucideIcon;
  children: ReactNode;
  className?: string;
  action?: ReactNode;
}) {
  const Icon = props.icon;
  return (
    <section className={`card ${props.className ?? ""}`.trim()}>
      {(props.title || props.action) && (
        <div className="card-head">
          {props.title && (
            <h2>
              {Icon && <Icon size={17} aria-hidden="true" />}
              {props.title}
            </h2>
          )}
          {props.action}
        </div>
      )}
      {props.children}
    </section>
  );
}

export interface Metric {
  value: ReactNode;
  label: string;
  sub?: string;
  href?: string;
  tone?: Tone;
}

/** The figures in one line, divided by hairlines, rather than a row of large boxes. */
export function Metrics({ metrics }: { metrics: Metric[] }) {
  return (
    <div className="metrics">
      {metrics.map((metric) => {
        const inside = (
          <>
            <span className="metric-value">{metric.value}</span>
            <span className="metric-label">{metric.label}</span>
            <span className="metric-sub">{metric.sub ?? ""}</span>
          </>
        );
        return metric.href ? (
          <a className="metric" key={metric.label} href={metric.href}>
            {inside}
          </a>
        ) : (
          <div className="metric" key={metric.label}>
            {inside}
          </div>
        );
      })}
    </div>
  );
}

export function Callout(props: { tone: "amber" | "blue"; children: ReactNode; action?: ReactNode }) {
  const Icon = props.tone === "amber" ? TriangleAlert : Info;
  return (
    <div className={`callout ${props.tone}`}>
      <Icon size={18} aria-hidden="true" />
      <div className="callout-text">{props.children}</div>
      {props.action}
    </div>
  );
}

export function Warnings(props: { warnings: string[] }) {
  return (
    <>
      {props.warnings.map((warning) => (
        <div key={warning} className="callout amber" role="alert">
          <TriangleAlert size={18} aria-hidden="true" />
          <div className="callout-text">{warning}</div>
        </div>
      ))}
    </>
  );
}

export function ExternalLink(props: { href: string; children: ReactNode }) {
  return (
    <a href={props.href} target="_blank" rel="noopener noreferrer" className="external">
      {props.children}
      <ExternalIcon size={13} aria-hidden="true" />
    </a>
  );
}

/** What the drafting settings say drafting is waiting for. */
export function DraftingSettings(props: { approvals: Approvals | null; withSender?: boolean }) {
  const a = props.approvals;
  if (!a) {
    return <p className="muted">The console was given no drafting settings, so it cannot say what drafting waits for.</p>;
  }
  return (
    <dl className="facts">
      <dt>Offer wording</dt>
      <dd>
        {a.offer ? (
          <Chip tone="green">Approved</Chip>
        ) : (
          <>
            <Chip tone="amber">Not approved</Chip> First drafts wait for your approval of the offer wording in the
            handbook.
          </>
        )}
      </dd>
      <dt>Follow-up wording</dt>
      <dd>
        {a.followups ? (
          <>
            <Chip tone="green">Approved</Chip> for one version of the handbook: a change to the handbook needs a new
            approval.
          </>
        ) : (
          <>
            <Chip tone="amber">Not approved</Chip> Follow-up drafts wait for your approval of the handbook's follow-up
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
