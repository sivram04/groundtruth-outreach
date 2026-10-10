import { Search, Send } from "lucide-react";
import { useMemo, useState } from "react";
import { CallError, sendDraft as defaultSendDraft } from "../api";
import { Avatar, PageHead, Status, draftTone, leadTone } from "../components";
import { SHOW, filterLeads, readFilter, type LeadFilter } from "../filters";
import { href, leadHref } from "../router";
import type { Snapshot } from "../types";

const PAGE_SIZE = 20;

export function Leads({
  data,
  query,
  onChanged,
  sendDraft = defaultSendDraft,
}: {
  data: Snapshot;
  query: URLSearchParams;
  onChanged?: () => void;
  sendDraft?: typeof defaultSendDraft;
}) {
  const filter = readFilter(query, data);
  const [words, setWords] = useState(filter.q);
  const rows = filterLeads(data, filter);
  const drafts = new Map(data.drafts.map((draft) => [draft.lead_id, draft]));
  const page = Math.max(1, Math.min(Number(query.get("page")) || 1, Math.max(1, Math.ceil(rows.length / PAGE_SIZE))));
  const visible = rows.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);
  const lastPage = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));

  // Batch approve: only a lead with a Gmail draft already CREATED (ready, unsent) can be selected.
  const batchable = useMemo(
    () =>
      new Set(
        visible
          .filter((lead) => !lead.cells["Sent at"] && lead.gmail_drafts?.some((d) => d.status === "CREATED"))
          .map((lead) => lead.id),
      ),
    [visible],
  );
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [results, setResults] = useState<{ lead_id: string; ok: boolean; why?: string }[] | null>(null);

  const go = (changes: Partial<LeadFilter> & { page?: number }) => {
    const next = { ...filter, ...changes };
    window.location.hash = href("/leads", {
      q: next.q,
      tier: next.tier,
      show: next.show === "all" ? "" : next.show,
      page: next.page && next.page > 1 ? String(next.page) : "",
    });
  };

  function toggle(id: string) {
    setResults(null);
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setResults(null);
    setSelected((prev) => (prev.size === batchable.size ? new Set() : new Set(batchable)));
  }

  async function approveSelected() {
    setBusy(true);
    const ids = [...selected];
    const outcome: { lead_id: string; ok: boolean; why?: string }[] = [];
    for (const id of ids) {
      try {
        await sendDraft(id);
        outcome.push({ lead_id: id, ok: true });
      } catch (e) {
        outcome.push({ lead_id: id, ok: false, why: e instanceof CallError ? e.message : "could not be sent" });
      }
    }
    setResults(outcome);
    setSelected(new Set());
    setConfirming(false);
    setBusy(false);
    onChanged?.();
  }

  return (
    <>
      <PageHead title="Leads" sub="Everyone in the A and B tabs, with where each stands." />
      <div className="toolbar">
        <form
          className="search"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            go({ q: words.trim(), page: 1 });
          }}
        >
          <Search size={16} aria-hidden="true" />
          <input
            type="search"
            value={words}
            onChange={(event) => setWords(event.target.value)}
            placeholder="Search company, contact or email"
            aria-label="Search leads"
            maxLength={100}
          />
          <button type="submit" className="small">
            Search
          </button>
        </form>
        <select value={filter.tier} onChange={(event) => go({ tier: event.target.value, page: 1 })} aria-label="Tier">
          <option value="">A and B</option>
          {data.tiers
            .filter((tier) => tier.prefix)
            .map((tier) => (
              <option key={tier.prefix} value={tier.prefix}>
                {tier.label}
              </option>
            ))}
        </select>
      </div>
      <nav className="tabs" aria-label="Show">
        {SHOW.map(([key, label]) => (
          <a
            key={key}
            href={href("/leads", { q: filter.q, tier: filter.tier, show: key === "all" ? "" : key })}
            className={filter.show === key ? "on" : undefined}
            aria-current={filter.show === key ? "true" : undefined}
          >
            {label}
          </a>
        ))}
      </nav>
      <p className="muted small" aria-live="polite">
        {rows.length} of {data.leads.length} leads
        {lastPage > 1 && ` · page ${page} of ${lastPage}`}
      </p>

      {data.send_enabled && (selected.size > 0 || results !== null) && (
        <div className="callout batch-bar">
          {results === null ? (
            confirming ? (
              <>
                <span>
                  Send {selected.size} email{selected.size === 1 ? "" : "s"} now?
                </span>
                <div className="email-actions">
                  <button type="button" className="primary" disabled={busy} onClick={approveSelected}>
                    <Send size={14} aria-hidden="true" /> {busy ? "Sending…" : `Yes, send ${selected.size}`}
                  </button>
                  <button type="button" className="secondary" disabled={busy} onClick={() => setConfirming(false)}>
                    Cancel
                  </button>
                </div>
              </>
            ) : (
              <>
                <span>{selected.size} selected</span>
                <button type="button" className="primary small" onClick={() => setConfirming(true)}>
                  <Send size={14} aria-hidden="true" /> Approve &amp; send {selected.size}
                </button>
              </>
            )
          ) : (
            <span>
              Sent {results.filter((r) => r.ok).length} of {results.length}
              {results.some((r) => !r.ok) && ` — ${results.filter((r) => !r.ok).length} failed; reload and retry those.`}
            </span>
          )}
        </div>
      )}

      <div className="card flush scroll">
        <table className="leads-table">
          <thead>
            <tr>
              {data.send_enabled && (
                <th scope="col" className="checkbox-col">
                  <input
                    type="checkbox"
                    aria-label="Select all ready to send on this page"
                    checked={batchable.size > 0 && selected.size === batchable.size}
                    disabled={batchable.size === 0}
                    onChange={toggleAll}
                  />
                </th>
              )}
              <th scope="col">Company</th>
              <th scope="col">Email</th>
              <th scope="col">Status</th>
              <th scope="col">Checks</th>
              <th scope="col">First sent</th>
              <th scope="col" className="num">
                Follow-ups
              </th>
              <th scope="col" className="num">
                Opens
              </th>
              <th scope="col" className="num">
                Clicks
              </th>
              <th scope="col">Next</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((lead) => {
              const draft = drafts.get(lead.id);
              return (
                <tr key={lead.id}>
                  {data.send_enabled && (
                    <td className="checkbox-col">
                      {batchable.has(lead.id) && (
                        <input
                          type="checkbox"
                          aria-label={`Select ${lead.company || lead.id} to send`}
                          checked={selected.has(lead.id)}
                          onChange={() => toggle(lead.id)}
                        />
                      )}
                    </td>
                  )}
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
                  <td className="small">
                    {lead.email || (lead.phone ? `☎ ${lead.phone}` : <span className="muted">no email yet</span>)}
                  </td>
                  <td>
                    <div className="chips">
                      <Status tone={leadTone(lead.status)}>{lead.status_label}</Status>
                      {lead.channel === "CALL" && <Status tone="amber">Call</Status>}
                      {lead.channel === "COMPANY_ONLY" && <Status tone="gray">No contact</Status>}
                      {draft && <Status tone={draftTone(draft.status)}>Draft: {draft.status_label.toLowerCase()}</Status>}
                      {lead.ready && !draft && <Status tone="green">Ready</Status>}
                      {lead.variant && <Status tone="blue">A/B: {lead.variant}</Status>}
                    </div>
                  </td>
                  <td className="small">
                    {lead.email_check || "-"} · {lead.fit || "-"}
                  </td>
                  <td className="nowrap small">{lead.cells["Sent at"] ?? ""}</td>
                  <td className="num">{lead.cells["Follow-ups sent"] ?? ""}</td>
                  <td className="num">{lead.cells["Opens (est.)"] ?? ""}</td>
                  <td className="num">{lead.cells["Clicks"] ?? ""}</td>
                  <td className="small next">{lead.action}</td>
                </tr>
              );
            })}
            {visible.length === 0 && (
              <tr>
                <td colSpan={data.send_enabled ? 10 : 9} className="muted">
                  No lead matches.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {lastPage > 1 && (
        <nav className="pager" aria-label="Pages">
          <button type="button" className="secondary small" disabled={page <= 1} onClick={() => go({ page: page - 1 })}>
            ← Previous
          </button>
          <span className="small muted">
            Page {page} of {lastPage}
          </span>
          <button
            type="button"
            className="secondary small"
            disabled={page >= lastPage}
            onClick={() => go({ page: page + 1 })}
          >
            Next →
          </button>
        </nav>
      )}
    </>
  );
}
