import { ArrowRight, BookOpen, Search, SlidersHorizontal, Sparkles, X } from "lucide-react";
import { useState } from "react";
import {
  Avatar,
  Callout,
  Card,
  CountTabs,
  ExternalLink,
  SectionHead,
  Status,
  draftTone,
  leadTone,
  type Tone,
} from "../components";
import { SHOW, filterLeads } from "../filters";
import { gmailSearch } from "../format";
import { href, leadHref } from "../router";
import type { Draft, Snapshot, TierCounts } from "../types";

// The tone of each kind of thing that needs the founder: an answer, something late, a draft,
// a check. The order numbers come from the server (console_model NEED_LABELS).
const NEED_TONES: Tone[] = ["green", "amber", "blue", "red"];

const NUMBERS: [keyof TierCounts, string][] = [
  ["leads", "Leads"],
  ["ready", "Ready for a first draft"],
  ["drafted", "Drafts written"],
  ["emailed", "Leads emailed"],
  ["emails_sent", "Emails sent, first emails and follow-ups"],
  ["replied", "Replied, including asked to stop"],
  ["reply_rate", "Reply rate"],
  ["opted_out", "Asked to stop"],
  ["bounced", "Bounced"],
  ["review_needed", "Emailed, match to check"],
  ["tracked", "Leads with a tracked email"],
  ["coverage", "Tracking coverage"],
  ["opened", "Opened (est.)"],
  ["open_rate", "Open rate (est.)"],
  ["clicked", "Clicked"],
  ["click_rate", "Click rate"],
];

const SHORT: Record<string, string> = { READY: "Ready", WAITING: "Waiting", HELD: "Held" };

/** A draft to read: who it is to, the line it opens from, and what it waits for. */
function DraftCard({ draft }: { draft: Draft }) {
  const tone = draftTone(draft.status);
  return (
    <article className={`match ${tone}`}>
      <div className="match-top">
        <span className="match-when" title={draft.prepared_at}>
          {draft.prepared_ago ? `written ${draft.prepared_ago}` : "written"}
        </span>
        <Status tone={tone}>{SHORT[draft.status] ?? draft.status_label}</Status>
      </div>
      <h3 title={draft.company}>{draft.company}</h3>
      <p className="match-line">{draft.quote ? `“${draft.quote}”` : draft.why[0] || "No opening line"}</p>
      <div className="match-foot">
        <span className="match-who">
          <Avatar name={draft.company} size="small" />
          <span className="match-who-text">
            {draft.contact || draft.to}
            <span className="block muted">{draft.to}</span>
          </span>
        </span>
        <a className="button small" href={leadHref(draft.lead_id)}>
          Read it
        </a>
      </div>
    </article>
  );
}

function Pipeline({ all }: { all: TierCounts }) {
  const steps: [string, number, string][] = [
    ["Leads", all.leads, href("/leads")],
    ["Email checked OK", all.checked_ok, href("/leads")],
    ["Company qualified", all.qualified, href("/leads")],
    ["Profiled", all.profiled, href("/leads")],
    ["Draft written", all.drafted, href("/drafts")],
    ["Emailed", all.emailed, href("/leads", { show: "emailed" })],
    ["Replied", all.replied, href("/leads", { show: "replied" })],
  ];
  const top = Math.max(1, ...steps.map(([, value]) => value));
  return (
    <ol className="pipeline">
      {steps.map(([label, value, link]) => (
        <li key={label}>
          <a href={link}>
            <span className="pipeline-label">{label}</span>
            <span className="pipeline-bar" aria-hidden="true">
              <span style={{ width: `${Math.max(value ? 2 : 0, (100 * value) / top)}%` }} />
            </span>
            <span className="pipeline-value">{value}</span>
          </a>
        </li>
      ))}
    </ol>
  );
}

export function Dashboard({ data }: { data: Snapshot }) {
  const [show, setShow] = useState("all");
  const [words, setWords] = useState("");
  const leads = new Map(data.leads.map((lead) => [lead.id, lead]));
  const drafts = new Map(data.drafts.map((draft) => [draft.lead_id, draft]));
  const all = data.tiers[data.tiers.length - 1];
  const account = data.links.gmail_account || data.signed_in_as;
  const waiting = data.drafts_summary.waiting_for_offer;
  const rows = filterLeads(data, { q: words, tier: "", show });
  return (
    <>
      {/* The screen leads with the filter bar, as the founder's reference does; the page still
          needs a name for anyone reading it with a screen reader. */}
      <h1 className="off-screen">Dashboard</h1>
      <div className="filters-card">
        <div className="filters-row">
          <span className="filters-what">
            <SlidersHorizontal size={15} aria-hidden="true" />
            Your leads
          </span>
          <div className="search">
            <Search size={15} aria-hidden="true" />
            <input
              type="search"
              value={words}
              onChange={(event) => setWords(event.target.value)}
              placeholder="Search a company, a contact or an address…"
              aria-label="Search leads"
              maxLength={100}
            />
            {words && (
              <button type="button" className="icon-button" onClick={() => setWords("")} aria-label="Clear the search">
                <X size={15} aria-hidden="true" />
              </button>
            )}
          </div>
        </div>
        <div className="filters-row bottom">
          <CountTabs
            label="Which leads"
            on={show}
            onPick={setShow}
            tabs={SHOW.map(([key, label]) => [key, label, filterLeads(data, { q: "", tier: "", show: key }).length])}
          />
          <span className="muted small">
            {data.today_text}
            {data.sync && ` · synced ${data.sync.at}`}
          </span>
        </div>
      </div>

      {waiting > 0 && (
        <Callout
          tone="amber"
          action={
            <a className="button small" href={href("/drafts")}>
              Read the drafts <ArrowRight size={14} aria-hidden="true" />
            </a>
          }
        >
          <strong>
            {waiting} {waiting === 1 ? "draft is" : "drafts are"} written and waiting for your approval of the offer
            wording.
          </strong>
        </Callout>
      )}

      {data.drafts.length > 0 && (
        <section className="strip">
          <SectionHead title="Drafts to read">
            <a className="button small ghost" href={href("/sources")}>
              <BookOpen size={14} aria-hidden="true" /> The handbook
            </a>
            <a className="button small" href={href("/drafts")}>
              <Sparkles size={14} aria-hidden="true" /> Read all {data.drafts.length}
              <ArrowRight size={14} aria-hidden="true" />
            </a>
          </SectionHead>
          <div className="matches">
            {data.drafts.slice(0, 5).map((draft) => (
              <DraftCard key={`${draft.lead_id}-${draft.kind}`} draft={draft} />
            ))}
          </div>
        </section>
      )}

      <section className="strip">
        <SectionHead title="All leads">
          <a className="button small ghost" href={href("/leads", { show })}>
            Open the leads page <ArrowRight size={14} aria-hidden="true" />
          </a>
        </SectionHead>
        <div className="card flush">
          <div className="scroll">
            <table className="leads-table">
              <thead>
                <tr>
                  <th scope="col">Company</th>
                  <th scope="col">Draft</th>
                  <th scope="col">Status</th>
                  <th scope="col">Next</th>
                  <th scope="col">First sent</th>
                </tr>
              </thead>
              <tbody>
                {rows.slice(0, 40).map((lead) => {
                  const draft = drafts.get(lead.id);
                  return (
                    <tr key={lead.id}>
                      <td>
                        <div className="who-cell">
                          <Avatar name={lead.company || lead.id} size="small" />
                          <div>
                            <a href={leadHref(lead.id)} className="strong">
                              {lead.company || lead.id}
                            </a>
                            <span className="small muted block">
                              {lead.contact ? `${lead.contact} · ` : ""}
                              {lead.email}
                            </span>
                          </div>
                        </div>
                      </td>
                      <td>
                        {draft ? (
                          <Status tone={draftTone(draft.status)}>{draft.status_label}</Status>
                        ) : (
                          <span className="muted">—</span>
                        )}
                      </td>
                      <td>
                        <Status tone={leadTone(lead.status)}>{lead.status_label}</Status>
                      </td>
                      <td className="small next" title={lead.action}>
                        {lead.action || "—"}
                      </td>
                      <td className="nowrap small muted" title={lead.cells["Sent at"] ?? ""}>
                        {lead.sent_ago || lead.cells["Sent at"] || "—"}
                      </td>
                    </tr>
                  );
                })}
                {rows.length === 0 && (
                  <tr>
                    <td colSpan={5} className="muted">
                      No lead matches.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
          {rows.length > 40 && (
            <p className="table-foot small muted">
              The first 40 of {rows.length}. <a href={href("/leads", { show })}>See them all on the Leads page.</a>
            </p>
          )}
        </div>
      </section>

      <div className="grid-dash">
        <Card title="Needs you">
          {data.needs_you.length === 0 ? (
            <p className="muted">Nothing needs you right now.</p>
          ) : (
            <ul className="needs">
              {data.needs_you.map((item) => {
                const lead = leads.get(item.lead_id);
                return (
                  <li key={`${item.lead_id}-${item.order}`}>
                    <Avatar name={lead?.company || item.lead_id} />
                    <div className="needs-main">
                      <div className="needs-line">
                        <a href={leadHref(item.lead_id)} className="strong">
                          {lead?.company || item.lead_id}
                        </a>
                        <Status tone={NEED_TONES[item.order] ?? "gray"}>{item.label}</Status>
                      </div>
                      <p>{item.text}</p>
                      <p className="small muted">
                        {item.lead_id}
                        {lead?.contact && ` · ${lead.contact}`}
                        {item.address && (
                          <>
                            {" · "}
                            <ExternalLink href={gmailSearch(item.address, account)}>
                              Open {item.address} in Gmail
                            </ExternalLink>
                          </>
                        )}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <div className="stack">
          <Card title="Coming up">
            {data.coming_up.length === 0 ? (
              <p className="muted">No follow-up is due in the next {data.coming_up_days} business days.</p>
            ) : (
              <ul className="timeline">
                {data.coming_up.map((item) => (
                  <li key={item.lead_id}>
                    <span className="timeline-day">{item.day}</span>
                    <span>
                      <a href={leadHref(item.lead_id)} className="strong">
                        {leads.get(item.lead_id)?.company || item.lead_id}
                      </a>
                      <span className="small muted block">{item.text}</span>
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Card>
          {all && (
            <Card title="Pipeline">
              <Pipeline all={all} />
            </Card>
          )}
        </div>
      </div>

      <details className="card">
        <summary>All the numbers, by tier</summary>
        <div className="scroll">
          <table>
            <thead>
              <tr>
                <th scope="col">Metric</th>
                {data.tiers.map((tier) => (
                  <th scope="col" className="num" key={tier.label}>
                    {tier.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {NUMBERS.map(([key, label]) => (
                <tr key={key}>
                  <td>{label}</td>
                  {data.tiers.map((tier) => (
                    <td className="num" key={tier.label}>
                      {key === "ready" && data.ready === null ? "?" : tier[key]}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <ul className="muted small notes">
          <li>
            A reply rate is over the leads emailed. Open and click rates are over the leads with a tracked email, never
            over everyone emailed.
          </li>
          {data.notes.map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      </details>
    </>
  );
}
