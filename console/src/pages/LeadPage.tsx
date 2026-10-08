import { ArrowLeft, Building2, History, Mail, Send, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { createGmailDraft, prepareDraft, sendDraft, CallError, type DraftStepResult, type SendResult } from "../api";
import { Avatar, Card, ExternalLink, Status, leadTone } from "../components";
import { DraftPreview } from "../draft-view";
import { gmailSearch, plural, safeHref } from "../format";
import { href } from "../router";
import type { Snapshot } from "../types";
import type { Lead } from "../types";
import { CallPanel } from "./CallPanel";
import { NotFound } from "./NotFound";
import { PostCallCandidate } from "./PostCallCandidate";
import { ReplyCandidate } from "./ReplyCandidate";

/** A value that changes on every snapshot refresh, so the open lead page re-checks its post-call candidate
 *  whenever the snapshot is re-read — which catches in-place changes the snapshot cannot fingerprint, such as
 *  the handbook being edited at the same URL or approved offer wording changing while approval stays true
 *  (the candidate endpoint rebuilds from the live handbook and settings). `generation` increments on every
 *  successful load, so this is reliable even within one clock minute (read_at is only minute precision). The
 *  call fields, suppression, offer flag and handbook URL are kept too for clarity. `PostCallCandidate`
 *  preserves the founder's edits when the re-fetched candidate is unchanged, and withdraws it when gone. */
export function postCallReloadKey(lead: Lead, data: Snapshot, generation = 0): string {
  return [
    generation,
    data.read_at ?? "",
    lead.call_history?.length ?? 0,
    lead.call_effect ?? "",
    lead.call_task?.id ?? "",
    lead.suppressed ? "1" : lead.suppressed === null ? "?" : "0",
    data.approvals?.offer ? "1" : "0",
    data.links?.handbook ?? "",
  ].join("|");
}

/** Approve-and-send: the one place a real email leaves, on the founder's click, for a draft already
 *  created in Gmail. Shown only when the server has send switched on. One click sends one email; a
 *  confirm step stands between the button and the send, and an already-sent lead just reports it. */
/** The steps that turn a ready lead into a sendable Gmail draft: prepare the candidate, review and
 *  approve it, then create the Gmail draft. Hidden once a Gmail draft exists (Approve-and-send takes over).
 *  `prepare`/`create` are injectable for tests. */
export function DraftWorkflow({
  lead,
  onChanged,
  prepare = prepareDraft,
  create = createGmailDraft,
}: {
  lead: Lead;
  onChanged?: () => void;
  prepare?: typeof prepareDraft;
  create?: typeof createGmailDraft;
}) {
  const [busy, setBusy] = useState("");
  const [prep, setPrep] = useState<DraftStepResult | null>(null);
  const [made, setMade] = useState(false);
  const [error, setError] = useState("");

  if (lead.gmail_drafts?.some((d) => d.status === "CREATED")) return null; // Approve-and-send takes over

  async function runPrepare() {
    setBusy("prepare");
    setError("");
    setMade(false);
    try {
      setPrep(await prepare(lead.id));
    } catch (e) {
      setError(e instanceof CallError ? e.message : "The draft could not be prepared.");
    } finally {
      setBusy("");
    }
  }

  async function runCreate() {
    setBusy("create");
    setError("");
    try {
      await create(lead.id);
      setMade(true);
      onChanged?.();
    } catch (e) {
      setError(e instanceof CallError ? e.message : "The draft could not be created.");
    } finally {
      setBusy("");
    }
  }

  return (
    <Card title="Prepare the draft" icon={Mail}>
      <ol className="plain small">
        <li>Prepare the draft for review.</li>
        <li>
          Review and approve it on the <a href={`#/review/${lead.id}`}>review page</a> (the offer wording must be
          approved too).
        </li>
        <li>Create the Gmail draft, then send it below.</li>
      </ol>
      <div className="email-actions">
        <button type="button" className="secondary" disabled={busy !== ""} onClick={runPrepare}>
          {busy === "prepare" ? "Preparing…" : "Prepare draft for review"}
        </button>
        <a className="button secondary" href={`#/review/${lead.id}`}>
          Open review
        </a>
        <button type="button" className="primary" disabled={busy !== ""} onClick={runCreate}>
          {busy === "create" ? "Creating…" : "Create Gmail draft"}
        </button>
      </div>
      {prep && (
        <p className="small">
          Candidate: <strong>{prep.status}</strong>
          {prep.why ? ` — ${prep.why}` : ""}
        </p>
      )}
      {made && <p className="small good">Gmail draft created — send it below.</p>}
      {error && <p className="callout amber">{error}</p>}
    </Card>
  );
}

export function ApproveAndSend({ lead, onChanged }: { lead: Lead; onChanged?: () => void }) {
  const created = lead.gmail_drafts?.find((item) => item.status === "CREATED");
  const alreadySent = Boolean(lead.cells["Sent at"]);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState<SendResult | null>(null);
  const [error, setError] = useState("");

  async function send() {
    setBusy(true);
    setError("");
    try {
      const result = await sendDraft(lead.id);
      setDone(result);
      setConfirming(false);
      onChanged?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The email could not be sent.");
    } finally {
      setBusy(false);
    }
  }

  if (done || alreadySent) {
    return (
      <Card title="Approve and send" icon={Send}>
        <p className="good">
          Sent{lead.email ? ` to ${lead.email}` : ""}
          {alreadySent && lead.cells["Sent at"] ? ` (${lead.cells["Sent at"]})` : ""}.
        </p>
        {done && !done.recorded && (
          <p className="callout amber">
            The email was sent, but recording it did not confirm. Reload before sending anything else.
          </p>
        )}
      </Card>
    );
  }

  if (!created) {
    return (
      <Card title="Approve and send" icon={Send}>
        <p className="muted">
          No draft is ready in Gmail yet. Review the draft first; once it is created you can send it here.
        </p>
      </Card>
    );
  }

  return (
    <Card title="Approve and send" icon={Send}>
      <p>
        One click sends this one email to <strong>{lead.email}</strong>. Nothing else is sent, and a second
        click can never send it twice.
      </p>
      {error && <p className="callout amber">{error}</p>}
      {confirming ? (
        <div className="email-actions">
          <button type="button" className="primary" disabled={busy} onClick={send}>
            <Send size={15} aria-hidden="true" /> {busy ? "Sending…" : `Yes, send to ${lead.email}`}
          </button>
          <button type="button" className="secondary" disabled={busy} onClick={() => setConfirming(false)}>
            Cancel
          </button>
        </div>
      ) : (
        <button type="button" className="primary" onClick={() => setConfirming(true)}>
          <Send size={15} aria-hidden="true" /> Approve and send
        </button>
      )}
    </Card>
  );
}

export function LeadPage({
  data,
  id,
  onChanged,
  generation = 0,
}: {
  data: Snapshot;
  id: string;
  onChanged?: () => void;
  generation?: number;
}) {
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
            {lead.variant && <Status tone="blue">A/B: {lead.variant}</Status>}
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

      {data.send_enabled && <DraftWorkflow lead={lead} onChanged={onChanged} />}
      {data.send_enabled && <ApproveAndSend lead={lead} onChanged={onChanged} />}

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
          <PostCallCandidate leadId={lead.id} reloadKey={postCallReloadKey(lead, data, generation)} />
        </>
      )}

      {data.reply_enabled && (
        <ReplyCandidate leadId={lead.id} reloadKey={postCallReloadKey(lead, data, generation)} />
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
