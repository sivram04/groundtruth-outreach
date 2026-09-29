import { Card, ExternalLink, Pill } from "../components";
import { gmailSearch } from "../format";
import { href, leadHref } from "../router";
import type { Snapshot, TierCounts } from "../types";

// The tone of each kind of thing that needs the founder: an answer, something late, a draft,
// a check. The order numbers come from the server (console_model NEED_LABELS).
const NEED_TONES = ["ok", "wait", "SENT", "warnish"];

const NUMBERS: [keyof TierCounts, string][] = [
  ["leads", "Leads"],
  ["ready", "Ready for a first draft"],
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

export function Dashboard({ data }: { data: Snapshot }) {
  const leads = new Map(data.leads.map((lead) => [lead.id, lead]));
  const all = data.tiers[data.tiers.length - 1];
  const tiles: [string | number, string, string][] = [
    [data.needs_you.length, "Need you", href("/leads", { show: "needs" })],
    [data.drafts.length, "Drafts waiting", href("/drafts")],
    [data.ready === null ? "?" : data.ready.length, "Ready for a first draft", href("/leads", { show: "ready" })],
    [all?.emailed ?? 0, "Leads emailed", href("/leads", { show: "emailed" })],
    [all?.replied ?? 0, `Replied (${all?.reply_rate ?? "-"})`, href("/leads", { show: "replied" })],
    [data.leads.length, "Leads", href("/leads")],
  ];
  return (
    <>
      <h1>Dashboard</h1>
      <p className="muted">
        Today is {data.today_text}.
        {data.sync && ` The mailbox sync last recorded a run at ${data.sync.at}.`}
      </p>

      <div className="tiles">
        {tiles.map(([value, label, link]) => (
          <a key={label} className="tile" href={link}>
            <b>{value}</b>
            <span>{label}</span>
          </a>
        ))}
      </div>

      <Card title="Needs you">
        {data.needs_you.length === 0 ? (
          <p className="muted">Nothing needs you right now.</p>
        ) : (
          <ul className="needs">
            {data.needs_you.map((item) => {
              const lead = leads.get(item.lead_id);
              return (
                <li key={`${item.lead_id}-${item.order}`}>
                  <div className="line">
                    <Pill tone={NEED_TONES[item.order] ?? ""}>{item.label}</Pill>
                    <a href={leadHref(item.lead_id)}>
                      <strong>{lead?.company || item.lead_id}</strong>
                    </a>
                    <span className="muted small">
                      {item.lead_id}
                      {lead?.contact && ` · ${lead.contact}`}
                    </span>
                  </div>
                  <p>{item.text}</p>
                  {item.address && (
                    <p className="small">
                      <ExternalLink href={gmailSearch(item.address, data.links.gmail_account || data.signed_in_as)}>
                        Open {item.address} in Gmail
                      </ExternalLink>
                    </p>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Card>

      {data.coming_up.length > 0 && (
        <Card title="Coming up">
          <p className="muted small">Follow-ups due in the next {data.coming_up_days} business days.</p>
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">Due</th>
                  <th scope="col">Lead</th>
                  <th scope="col">Company</th>
                  <th scope="col">What</th>
                </tr>
              </thead>
              <tbody>
                {data.coming_up.map((item) => (
                  <tr key={item.lead_id}>
                    <td className="nowrap">{item.day}</td>
                    <td>
                      <a href={leadHref(item.lead_id)}>{item.lead_id}</a>
                    </td>
                    <td>{leads.get(item.lead_id)?.company}</td>
                    <td className="small">{item.text}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}

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
