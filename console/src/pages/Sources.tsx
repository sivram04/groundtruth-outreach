import { Card, DraftingSettings, ExternalLink } from "../components";
import type { Snapshot } from "../types";

export function Sources({ data }: { data: Snapshot }) {
  return (
    <>
      <h1>Sources</h1>
      <p className="muted">Where everything on these pages comes from.</p>

      <Card title="Leads Sheet">
        <p>
          <ExternalLink href={data.links.sheet}>Open the leads Sheet</ExternalLink>
        </p>
        <dl className="facts">
          {data.tiers
            .filter((tier) => tier.prefix)
            .map((tier) => (
              <div className="pair" key={tier.prefix}>
                <dt>{tier.label}</dt>
                <dd>{tier.leads} leads with a Lead ID</dd>
              </div>
            ))}
          <dt>Events</dt>
          <dd>{data.event_count} recorded</dd>
          <dt>Suppression</dt>
          <dd>
            {data.suppression_count === null ? "cannot be read" : `${data.suppression_count} addresses or domains`}
          </dd>
        </dl>
      </Card>

      <Card title="Scheduled jobs">
        <dl className="facts">
          <dt>Mailbox sync</dt>
          <dd>
            Every 10 minutes it reads the mailbox, never writing to it, and records sends, replies, bounces and requests
            to stop in the Sheet.{" "}
            {data.sync ? `Last recorded run: ${data.sync.at} (${data.sync.result}).` : "No run recorded yet."} A run
            that finds nothing records a row only every 6 hours.
          </dd>
          <dt>Tracking</dt>
          <dd>
            Every 5 minutes it turns opens and clicks into events.{" "}
            {data.tracking_run
              ? `Last recorded run: ${data.tracking_run.at} (${data.tracking_run.result}).`
              : "No run recorded yet."}
          </dd>
        </dl>
      </Card>

      <Card title="Handbook">
        <p>
          {data.links.handbook ? (
            <ExternalLink href={data.links.handbook}>Open the handbook in Drive</ExternalLink>
          ) : (
            "The console was not told where the handbook is."
          )}
        </p>
        <p className="muted small">
          Drafting takes the offer and follow-up wording from this document. The console does not read it yet.
        </p>
      </Card>

      <Card title="Drafting settings">
        <DraftingSettings approvals={data.approvals} withSender />
      </Card>

      <Card title="Coming next">
        <ul>
          <li>Drafts you can open, change, approve and send, one at a time.</li>
          <li>Choosing another Sheet or handbook, and uploading a list of leads.</li>
        </ul>
      </Card>
    </>
  );
}
