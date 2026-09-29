import { ArrowRight, CalendarClock, Flag, Mail, MailOpen, Reply, Send, Workflow } from "lucide-react";
import { Avatar, Callout, Card, Chip, ExternalLink, PageHead, StatCard, type Tone } from "../components";
import { gmailSearch } from "../format";
import { href, leadHref } from "../router";
import type { Snapshot, TierCounts } from "../types";

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
  const leads = new Map(data.leads.map((lead) => [lead.id, lead]));
  const all = data.tiers[data.tiers.length - 1];
  const account = data.links.gmail_account || data.signed_in_as;
  const waiting = data.drafts_summary.waiting_for_offer;
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

      <div className="stats">
        <StatCard icon={Flag} tone="red" value={data.needs_you.length} label="Need you" href={href("/leads", { show: "needs" })} />
        <StatCard
          icon={Mail}
          tone="amber"
          value={data.drafts.length}
          label="Drafts"
          sub={`${data.drafts_summary.waiting} waiting for you`}
          href={href("/drafts")}
        />
        <StatCard
          icon={Send}
          tone="blue"
          value={all?.emailed ?? 0}
          label="Leads emailed"
          sub={`${all?.emails_sent ?? 0} emails in all`}
          href={href("/leads", { show: "emailed" })}
        />
        <StatCard
          icon={Reply}
          tone="green"
          value={all?.replied ?? 0}
          label="Replied"
          sub={`Reply rate ${all?.reply_rate ?? "-"}`}
          href={href("/leads", { show: "replied" })}
        />
        <StatCard
          icon={MailOpen}
          tone="violet"
          value={all?.opened ?? 0}
          label="Opened (est.)"
          sub={all?.tracked ? `of ${all.tracked} tracked` : "nothing tracked yet"}
        />
      </div>

      <div className="grid-dash">
        <Card title="Needs you" icon={Flag}>
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
                        <Chip tone={NEED_TONES[item.order] ?? "gray"}>{item.label}</Chip>
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
            <Card title="Pipeline" icon={Workflow}>
              <Pipeline all={all} />
            </Card>
          )}
          <Card title="Coming up" icon={CalendarClock}>
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

      <Card title="Numbers">
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
      </Card>
    </>
  );
}
