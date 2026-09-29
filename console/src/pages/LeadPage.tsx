import { Card, ExternalLink, Pill } from "../components";
import { gmailSearch, plural, safeHref } from "../format";
import { href } from "../router";
import type { Snapshot } from "../types";
import { NotFound } from "./NotFound";

export function LeadPage({ data, id }: { data: Snapshot; id: string }) {
  const lead = data.leads.find((item) => item.id === id);
  if (!lead) return <NotFound what={`There is no lead ${id}.`} />;
  const account = data.links.gmail_account || data.signed_in_as;
  const site = safeHref(lead.website_href);
  const tracked = lead.cells["Tracked sends"];
  return (
    <>
      <p className="small">
        <a href={href("/leads")}>All leads</a>
      </p>
      <h1>{lead.company || lead.id}</h1>
      <p className="muted">
        {lead.id}
        {lead.tier_label && ` · ${lead.tier_label}`} · <Pill tone={lead.status}>{lead.status_label}</Pill>
      </p>
      {lead.error && <p className="warn">Where this lead stands could not be worked out: {lead.error}</p>}

      {lead.action && (
        <Card title="Next">
          <p>{lead.action}</p>
        </Card>
      )}

      <Card title="The lead">
        <dl className="facts">
          <dt>Contact</dt>
          <dd>{lead.contact || "-"}</dd>
          <dt>Email</dt>
          <dd>
            {lead.email ? (
              <>
                {lead.email} · <ExternalLink href={gmailSearch(lead.email, account)}>Open in Gmail</ExternalLink>
              </>
            ) : (
              "-"
            )}
          </dd>
          <dt>Website</dt>
          <dd>{site ? <ExternalLink href={site}>{lead.website}</ExternalLink> : lead.website || "-"}</dd>
          <dt>Email check</dt>
          <dd>
            {lead.email_check || "not done"}
            {lead.email_reason && `: ${lead.email_reason}`}
          </dd>
          <dt>Fit</dt>
          <dd>
            {lead.fit || "not researched"}
            {lead.fit_reason && `: ${lead.fit_reason}`}
          </dd>
          <dt>Company profile</dt>
          <dd>{lead.profile || "not done"}</dd>
          <dt>On hold</dt>
          <dd>{lead.hold ? `yes: ${lead.hold}` : "no"}</dd>
          <dt>Suppressed</dt>
          <dd>{lead.suppressed === null ? "cannot tell" : lead.suppressed ? "yes" : "no"}</dd>
        </dl>
      </Card>

      <Card title="Emails">
        <dl className="facts">
          <dt>Sent to</dt>
          <dd>{lead.cells["Sent to"] || "-"}</dd>
          <dt>First sent</dt>
          <dd>{lead.cells["Sent at"] || "-"}</dd>
          <dt>Follow-ups sent</dt>
          <dd>{lead.cells["Follow-ups sent"] || "-"}</dd>
          <dt>Replied</dt>
          <dd>{lead.cells["Replied at"] || "-"}</dd>
          <dt>Opens and clicks</dt>
          <dd>
            {tracked
              ? `${lead.cells["Opens (est.)"]} opens (an estimate) and ${lead.cells["Clicks"]} clicks, over ${plural(
                  Number(tracked),
                  "tracked email",
                )}`
              : "Not tracked"}
          </dd>
        </dl>
      </Card>

      <Card title="First draft">
        {lead.ready ? (
          <p>
            <Pill tone="ok">Ready</Pill> Every check on the lead passes. A draft also needs a usable quote about the
            company, judged when it is written.
          </p>
        ) : lead.blockers.length > 0 ? (
          <>
            <p>Not ready:</p>
            <ul>
              {lead.blockers.map((why) => (
                <li key={why}>{why}</li>
              ))}
            </ul>
          </>
        ) : (
          <p className="muted">Cannot tell.</p>
        )}
      </Card>

      <Card title="History">
        {lead.events.length === 0 ? (
          <p className="muted">Nothing recorded yet.</p>
        ) : (
          <div className="scroll">
            <table>
              <thead>
                <tr>
                  <th scope="col">When</th>
                  <th scope="col">What</th>
                  <th scope="col">Which email</th>
                  <th scope="col">Address</th>
                  <th scope="col">Tied to the lead by</th>
                  <th scope="col">Detail</th>
                </tr>
              </thead>
              <tbody>
                {lead.events.map((event, index) => (
                  <tr key={index}>
                    <td className="nowrap">{event.when}</td>
                    <td>{event.event}</td>
                    <td>{event.step}</td>
                    <td>{event.address}</td>
                    <td>{event.match}</td>
                    <td className="small">{event.detail}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <details className="card">
        <summary>Every column of this lead in the Sheet</summary>
        <dl className="facts">
          {lead.columns.map(([column, value]) => (
            <div className="pair" key={column}>
              <dt>{column}</dt>
              <dd>{value || "-"}</dd>
            </div>
          ))}
        </dl>
      </details>
    </>
  );
}
