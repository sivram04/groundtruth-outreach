import { ArrowLeft, Building2, History, Mail, Send, ShieldCheck } from "lucide-react";
import { Avatar, Card, ExternalLink, Status, leadTone } from "../components";
import { DraftPreview } from "../draft-view";
import { gmailSearch, plural, safeHref } from "../format";
import { href } from "../router";
import type { Snapshot } from "../types";
import type { Lead } from "../types";
import { CallPanel } from "./CallPanel";
import { NotFound } from "./NotFound";
import { PostCallCandidate } from "./PostCallCandidate";

/** A value that changes on every snapshot refresh (via `read_at`), so the open lead page re-checks its
 *  post-call candidate whenever the snapshot is re-read — which catches in-place changes the snapshot cannot
 *  fingerprint, such as the handbook being edited at the same URL or approved offer wording changing while
 *  approval stays true (the candidate endpoint rebuilds from the live handbook and settings). The call
 *  fields, suppression, offer flag and handbook URL are kept too for clarity. `PostCallCandidate` preserves
 *  the founder's edits when the re-fetched candidate is unchanged, and withdraws it when it is gone. */
export function postCallReloadKey(lead: Lead, data: Snapshot): string {
  return [
    data.read_at ?? "",
    lead.call_history?.length ?? 0,
    lead.call_effect ?? "",
    lead.call_task?.id ?? "",
    lead.suppressed ? "1" : lead.suppressed === null ? "?" : "0",
    data.approvals?.offer ? "1" : "0",
    data.links?.handbook ?? "",
  ].join("|");
}

export function LeadPage({ data, id, onChanged }: { data: Snapshot; id: string; onChanged?: () => void }) {
  const lead = data.leads.find((item) => item.id === id);
  if (!lead) return <NotFound what={`There is no lead ${id}.`} />;
  const account = data.links.gmail_account || data.signed_in_as;
  const site = safeHref(lead.website_href);
  const tracked = lead.cells["Tracked sends"];
  const draft = data.drafts.find((item) => item.lead_id === lead.id);
  return (
    <>
      <a className="back small" href={href("/leads")}>
        <ArrowLeft size={14} aria-hidden="true" /> All leads
      </a>
      <div className="lead-head">
        <Avatar name={lead.company || lead.id} size="large" />
        <div>
          <h1>{lead.company || lead.id}</h1>
          <p className="muted">
            {lead.id}
            {lead.tier_label && ` · ${lead.tier_label}`}
            {lead.contact && ` · ${lead.contact}`}
          </p>
          <div className="chips">
            <Status tone={leadTone(lead.status)}>{lead.status_label}</Status>
            {lead.ready && <Status tone="green">Ready for a first draft</Status>}
          </div>
        </div>
      </div>
      {lead.error && <p className="callout amber">Where this lead stands could not be worked out: {lead.error}</p>}

      {lead.action && (
        <Card title="Next" icon={Send} className="next-card">
          <p>{lead.action}</p>
        </Card>
      )}

      {draft && (
        <Card title="The draft" icon={Mail}>
          <DraftPreview draft={draft} from={data.approvals?.sender || account} />
        </Card>
      )}

      <div className="grid-2">
        <Card title="The lead" icon={Building2}>
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
            <dt>Phone</dt>
            <dd>{lead.phone || "-"}</dd>
            <dt>How to reach</dt>
            <dd>
              {lead.channel === "CALL"
                ? "Call: no email on file"
                : lead.channel === "COMPANY_ONLY"
                  ? "No contact yet — find one"
                  : "Email"}
            </dd>
            <dt>Website</dt>
            <dd>{site ? <ExternalLink href={site}>{lead.website}</ExternalLink> : lead.website || "-"}</dd>
            <dt>Company profile</dt>
            <dd>{lead.profile || "not done"}</dd>
            <dt>On hold</dt>
            <dd>{lead.hold ? `yes: ${lead.hold}` : "no"}</dd>
            <dt>Suppressed</dt>
            <dd>{lead.suppressed === null ? "cannot tell" : lead.suppressed ? "yes" : "no"}</dd>
          </dl>
        </Card>

        <Card title="Checks" icon={ShieldCheck}>
          <dl className="facts">
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
            <dt>First draft</dt>
            <dd>
              {lead.ready ? (
                "Every check on the lead passes. A draft also needs a usable quote about the company."
              ) : lead.blockers.length > 0 ? (
                <ul className="plain">
                  {lead.blockers.map((why) => (
                    <li key={why}>{why}</li>
                  ))}
                </ul>
              ) : (
                "cannot tell"
              )}
            </dd>
          </dl>
        </Card>
      </div>

      {data.calls_enabled && (
        <>
          <CallPanel
            leadId={lead.id}
            phone={lead.phone}
            task={lead.call_task ?? null}
            history={lead.call_history}
            effectSaid={lead.call_effect_said}
            onChanged={onChanged ?? (() => {})}
          />
          <PostCallCandidate leadId={lead.id} reloadKey={postCallReloadKey(lead, data)} />
        </>
      )}

      <Card title="Emails" icon={Mail}>
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

      <Card title="History" icon={History}>
        {lead.events.length === 0 ? (
          <p className="muted">Nothing recorded yet.</p>
        ) : (
          <ol className="history">
            {lead.events.map((event, index) => (
              <li key={index}>
                <span className="history-when">{event.when}</span>
                <span>
                  <strong>{event.event}</strong>
                  {event.step && <span className="muted"> · {event.step}</span>}
                  <span className="block small muted">
                    {event.address}
                    {event.match && ` · tied to the lead by ${event.match}`}
                  </span>
                  {event.detail && <span className="block small">{event.detail}</span>}
                </span>
              </li>
            ))}
          </ol>
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
