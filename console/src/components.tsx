import {
  Database,
  ExternalLink as ExternalIcon,
  Info,
  LayoutDashboard,
  Mail,
  RefreshCw,
  TriangleAlert,
  Users,
  type LucideIcon,
} from "lucide-react";
import type { ReactNode } from "react";
import { NAME } from "./brand";
import type { Page } from "./router";
import type { Approvals } from "./types";

const NAV: [Page, string, string, LucideIcon][] = [
  ["dashboard", "#/", "Dashboard", LayoutDashboard],
  ["drafts", "#/drafts", "Drafts", Mail],
  ["leads", "#/leads", "Leads", Users],
  ["sources", "#/sources", "Sources", Database],
];

export function Layout(props: {
  page: Page;
  signedInAs: string;
  readAt: string;
  refreshing: boolean;
  draftsWaiting: number;
  onRefresh: () => void;
  children: ReactNode;
}) {
  const active = props.page === "lead" ? "leads" : props.page;
  return (
    <div className="shell">
      <aside className="sidebar">
        <a className="brand" href="#/">
          <span className="brand-mark" aria-hidden="true">
            {NAME.slice(0, 1)}
          </span>
          <span>{NAME}</span>
        </a>
        <nav aria-label="Pages">
          {NAV.map(([page, link, label, Icon]) => (
            <a
              key={page}
              href={link}
              className={active === page ? "on" : undefined}
              aria-current={active === page ? "page" : undefined}
            >
              <Icon size={18} aria-hidden="true" />
              <span className="label">{label}</span>
              {page === "drafts" && props.draftsWaiting > 0 && (
                <span className="count" aria-label={`${props.draftsWaiting} drafts`}>
                  {props.draftsWaiting}
                </span>
              )}
            </a>
          ))}
        </nav>
        <div className="sidebar-foot">
          {props.signedInAs && (
            <div className="who" title={props.signedInAs}>
              <span className="avatar small" aria-hidden="true">
                {props.signedInAs.slice(0, 1).toUpperCase()}
              </span>
              <span className="who-text">{props.signedInAs}</span>
            </div>
          )}
        </div>
      </aside>
      <div className="content">
        <div className="topbar">
          <span className="muted small">{props.readAt && `Read from the Sheet at ${props.readAt}`}</span>
          <button type="button" className="ghost" onClick={props.onRefresh} disabled={props.refreshing}>
            <RefreshCw size={15} aria-hidden="true" className={props.refreshing ? "spin" : undefined} />
            {props.refreshing ? "Reading…" : "Refresh"}
          </button>
        </div>
        <main>{props.children}</main>
        <footer>Nothing on these pages changes the Sheet or Gmail.</footer>
      </div>
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

const AVATAR_COLORS = ["c1", "c2", "c3", "c4", "c5", "c6"];

/** Two letters for a company, and a colour that stays the same for it. */
export function Avatar(props: { name: string; size?: "small" | "large" }) {
  const words = props.name.replace(/<[^>]*>/g, " ").match(/[A-Za-z0-9]+/g) ?? [];
  const letters = (words.length > 1 ? (words[0]![0] ?? "") + (words[1]![0] ?? "") : (words[0] ?? "?").slice(0, 2))
    .toUpperCase();
  let hash = 0;
  for (const character of props.name) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  const color = AVATAR_COLORS[hash % AVATAR_COLORS.length];
  return (
    <span className={`avatar ${color} ${props.size ?? ""}`.trim()} aria-hidden="true">
      {letters}
    </span>
  );
}

export function Card(props: { title?: string; icon?: LucideIcon; children: ReactNode; className?: string; action?: ReactNode }) {
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

export function StatCard(props: { icon: LucideIcon; tone: Tone; value: ReactNode; label: string; sub?: string; href?: string }) {
  const Icon = props.icon;
  const inner = (
    <>
      <span className={`stat-icon ${props.tone}`} aria-hidden="true">
        <Icon size={18} />
      </span>
      <span className="stat-value">{props.value}</span>
      <span className="stat-label">{props.label}</span>
      {props.sub && <span className="stat-sub">{props.sub}</span>}
    </>
  );
  return props.href ? (
    <a className="stat" href={props.href}>
      {inner}
    </a>
  ) : (
    <div className="stat">{inner}</div>
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
