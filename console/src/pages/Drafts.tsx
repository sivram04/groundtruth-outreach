import { Inbox, MailOpen } from "lucide-react";
import { useCallback, useState } from "react";
import { Avatar, Callout, Card, Chip, DraftingSettings, PageHead, draftTone } from "../components";
import { DraftDrawer, DraftPreview } from "../draft-view";
import { leadHref } from "../router";
import type { Draft, Snapshot } from "../types";

function DraftRow(props: { draft: Draft; on: boolean; onPeek: () => void; onOpen: () => void }) {
  const { draft } = props;
  return (
    <li>
      <button
        type="button"
        className={`draft-row${props.on ? " on" : ""}`}
        onMouseEnter={props.onPeek}
        onFocus={props.onPeek}
        onClick={props.onOpen}
      >
        <Avatar name={draft.company} />
        <span className="draft-main">
          <span className="draft-line">
            <span className="draft-company">{draft.company}</span>
            <Chip tone={draftTone(draft.status)}>{draft.status_label}</Chip>
          </span>
          <span className="draft-subject">
            {draft.quote ? `“${draft.quote}”` : draft.why[0] || "No opening line"}
          </span>
          <span className="draft-to">
            {draft.contact && `${draft.contact} · `}
            {draft.to}
          </span>
        </span>
      </button>
    </li>
  );
}

export function Drafts({ data }: { data: Snapshot }) {
  const [peeked, setPeeked] = useState<string | null>(null);
  const [opened, setOpened] = useState<string | null>(null);
  const close = useCallback(() => setOpened(null), []);
  const drafts = data.drafts;
  const shown = drafts.find((draft) => draft.lead_id === peeked) ?? drafts[0];
  const open = drafts.find((draft) => draft.lead_id === opened);
  const from = data.approvals?.sender || data.links.gmail_account;
  const summary = data.drafts_summary;
  const ready = data.ready?.map((id) => data.leads.find((lead) => lead.id === id)).filter((lead) => lead !== undefined);
  const notYetWritten = ready?.filter((lead) => !lead.draft) ?? [];
  return (
    <>
      <PageHead
        title="Drafts"
        sub={
          drafts.length
            ? "Hover over a draft to read it here; click it to open it."
            : "Each ready lead's first email will be written here for you to read."
        }
      >
        <div className="chips">
          <Chip tone="green">{summary.ready} ready to approve</Chip>
          <Chip tone="amber">{summary.waiting} waiting for you</Chip>
          <Chip tone="red">{summary.held} held</Chip>
        </div>
      </PageHead>

      {summary.waiting_for_offer > 0 && (
        <Callout tone="amber">
          <strong>
            {summary.waiting_for_offer} {summary.waiting_for_offer === 1 ? "draft is" : "drafts are"} written and
            waiting for your approval of the offer wording.
          </strong>{" "}
          Nothing can be sent until you approve it. Approving the wording, then each email, comes next.
        </Callout>
      )}

      {drafts.length === 0 ? (
        <Card className="empty">
          <Inbox size={34} aria-hidden="true" />
          <h2>No drafts yet</h2>
          <p className="muted">When drafts are prepared, each ready lead's first email appears here.</p>
        </Card>
      ) : (
        <div className="drafts-split">
          <ul className="draft-list" aria-label="Drafts">
            {drafts.map((draft) => (
              <DraftRow
                key={`${draft.lead_id}-${draft.kind}`}
                draft={draft}
                on={draft.lead_id === shown?.lead_id}
                onPeek={() => setPeeked(draft.lead_id)}
                onOpen={() => setOpened(draft.lead_id)}
              />
            ))}
          </ul>
          <aside className="draft-pane" aria-label="The draft you are pointing at">
            {shown && (
              <>
                <p className="pane-note muted small">
                  <MailOpen size={14} aria-hidden="true" /> {shown.company}
                  {" · "}
                  <a href={leadHref(shown.lead_id)}>{shown.lead_id}</a>
                </p>
                <DraftPreview draft={shown} from={from} />
              </>
            )}
          </aside>
        </div>
      )}

      {open && <DraftDrawer draft={open} from={from} onClose={close} />}

      <div className="grid-2">
        <Card title="What drafting waits for">
          <DraftingSettings approvals={data.approvals} />
        </Card>
        <Card title={`Ready, not written yet${ready ? `: ${notYetWritten.length}` : ""}`}>
          <p className="muted small">
            Email checked OK, company qualified and profiled, never emailed, not on hold or suppressed. A draft also
            needs a usable quote about the company, judged when it is written.
          </p>
          {ready === undefined ? (
            <p className="muted">This cannot be told: the Suppression tab cannot be read.</p>
          ) : notYetWritten.length === 0 ? (
            <p className="muted">Every ready lead has a draft.</p>
          ) : (
            <ul className="mini-list">
              {notYetWritten.map((lead) => (
                <li key={lead.id}>
                  <Avatar name={lead.company} size="small" />
                  <a href={leadHref(lead.id)}>{lead.company || lead.id}</a>
                  <span className="muted small">{lead.email}</span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
