import { ArrowRight, Search, X } from "lucide-react";
import { useState } from "react";
import { Avatar, Callout, Card, ExternalLink, Metrics, PageHead, Status, draftTone, leadTone, type Tone } from "../components";
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

/** A draft as a card: who it is to, the line it opens from, and what it waits for. */
function DraftCard({ draft }: { draft: Draft }) {
  return (
    <a className="draft-card" href={leadHref(draft.lead_id)}>
      <div className="draft-card-top">
        <Avatar name={draft.company} size="small" />
        <h3>{draft.company}</h3>
      </div>
      <p className="draft-card-line">
        {draft.quote ? `“${draft.quote}”` : draft.why[0] || "No opening line"}
      </p>
      <p className="draft-card-to">
        {draft.contact && `${draft.contact} · `}
        {draft.to}
      </p>
      <div className="draft-card-foot">
        <Status tone={draftTone(draft.status)}>{draft.status_label}</Status>
        <span className="draft-card-open">Read it</span>
      </div>
    </a>
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
      <PageHead
        title="Dashboard"
        sub={`${data.today_text}${data.sync ? ` · the mailbox sync last recorded a run at ${data.sync.at}` : ""}`}
      />

      {waiting > 0 && (
        <Callout
          tone="amber"
          action={
            <a className="button small" href={href("/drafts")}>
              Read the drafts <ArrowRight size={15} aria-hidden="true" />
            </a>
          }
        >
          <strong>
            {waiting} {waiting === 1 ? "draft is" : "drafts are"} written and waiting for your approval of the offer
            wording.
          </strong>
        </Callout>
      )}

      <Metrics
        metrics={[
          { value: data.needs_you.length, label: "Need you", href: href("/leads", { show: "needs" }) },
          {
            value: data.drafts.length,
            label: "Drafts",
            sub: `${data.drafts_summary.waiting} waiting for you`,
            href: href("/drafts"),
          },
          {
            value: all?.emailed ?? 0,
            label: "Leads emailed",
            sub: `${all?.emails_sent ?? 0} emails in all`,
            href: href("/leads", { show: "emailed" }),
          },
          {
            value: all?.replied ?? 0,
            label: "Replied",
            sub: `Reply rate ${all?.reply_rate ?? "-"}`,
            href: href("/leads", { show: "replied" }),
          },
          {
            value: all?.opened ?? 0,
            label: "Opened (est.)",
            sub: all?.tracked ? `of ${all.tracked} tracked` : "nothing tracked yet",
          },
        ]}
      />

      {data.drafts.length > 0 && (
        <section className="strip">
          <div className="strip-head">
            <h2>Drafts to read</h2>
            <a className="button small ghost" href={href("/drafts")}>
              Read them all <ArrowRight size={15} aria-hidden="true" />
            </a>
          </div>
          <div className="draft-cards">
            {data.drafts.slice(0, 5).map((draft) => (
              <DraftCard key={`${draft.lead_id}-${draft.kind}`} draft={draft} />
            ))}
          </div>
        </section>
      )}

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
          {all && (
            <Card title="Pipeline">
              <Pipeline all={all} />
            </Card>
          )}
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
        </div>
      </div>

      <section className="card flush">
        <div className="table-head">
          <div className="table-tabs" role="tablist" aria-label="Which leads">
            {SHOW.map(([key, label]) => (
              <button
                key={key}
                type="button"
                role="tab"
                aria-selected={show === key}
                className={show === key ? "on" : undefined}
                onClick={() => setShow(key)}
              >
                {label}
                <span className="tab-count">{filterLeads(data, { q: "", tier: "", show: key }).length}</span>
              </button>
            ))}
          </div>
          <div className="search small">
            <Search size={15} aria-hidden="true" />
            <input
              type="search"
              value={words}
              onChange={(event) => setWords(event.target.value)}
              placeholder="Search company…"
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
        <div className="scroll">
          <table className="leads-table">
            <thead>
              <tr>
                <th scope="col">Company</th>
                <th scope="col">Draft</th>
                <th scope="col">Status</th>
                <th scope="col">First sent</th>
                <th scope="col">Next</th>
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
                            {lead.id}
                            {lead.contact && ` · ${lead.contact}`}
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
                    <td className="nowrap small">{lead.cells["Sent at"] || "—"}</td>
                    <td className="small next">{lead.action}</td>
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
      </section>

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
