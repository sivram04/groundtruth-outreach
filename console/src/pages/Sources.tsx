import { BookOpen, CalendarClock, Settings, Sheet, Sparkles } from "lucide-react";
import { Card, DraftingSettings, ExternalLink, PageHead } from "../components";
import type { Snapshot } from "../types";

export function Sources({ data }: { data: Snapshot }) {
  return (
    <>
      <PageHead title="Sources" sub="Where everything on these pages comes from." />
      <div className="grid-2">
        <Card title="Leads Sheet" icon={Sheet}>
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
            <dt>Drafts</dt>
            <dd>{data.drafts.length} in the Drafts tab</dd>
            <dt>Events</dt>
            <dd>{data.event_count} recorded</dd>
            <dt>Suppression</dt>
            <dd>
              {data.suppression_count === null ? "cannot be read" : `${data.suppression_count} addresses or domains`}
            </dd>
          </dl>
        </Card>

        <Card title="Handbook" icon={BookOpen}>
          <p>
            {data.links.handbook ? (
              <ExternalLink href={data.links.handbook}>Open the handbook in Drive</ExternalLink>
            ) : (
              "The console was not told where the handbook is."
            )}
          </p>
          <p className="muted small">
            Drafts take the offer and follow-up wording from this document, and each opening line only from a quote on
            the lead's own website.
          </p>
        </Card>

        <Card title="Scheduled jobs" icon={CalendarClock}>
          <dl className="facts">
            <dt>Mailbox sync</dt>
            <dd>
              Every 10 minutes it reads the mailbox, never writing to it, and records sends, replies, bounces and
              requests to stop.{" "}
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

        <Card title="Drafting settings" icon={Settings}>
          <DraftingSettings approvals={data.approvals} withSender />
        </Card>
      </div>

      <Card title="Coming next" icon={Sparkles}>
        <ul className="plain">
          <li>Approve the offer wording here, then edit a draft and approve it: approving sends that one email.</li>
          <li>Choosing another Sheet or handbook, and uploading a list of leads.</li>
        </ul>
      </Card>
    </>
  );
}
