import { Search } from "lucide-react";
import { useState } from "react";
import { Avatar, PageHead, Status, draftTone, leadTone } from "../components";
import { SHOW, filterLeads, readFilter, type LeadFilter } from "../filters";
import { href, leadHref } from "../router";
import type { Snapshot } from "../types";

export function Leads({ data, query }: { data: Snapshot; query: URLSearchParams }) {
  const filter = readFilter(query, data);
  const [words, setWords] = useState(filter.q);
  const rows = filterLeads(data, filter);
  const drafts = new Map(data.drafts.map((draft) => [draft.lead_id, draft]));
  const go = (changes: Partial<LeadFilter>) => {
    const next = { ...filter, ...changes };
    window.location.hash = href("/leads", { q: next.q, tier: next.tier, show: next.show === "all" ? "" : next.show });
  };
  return (
    <>
      <PageHead title="Leads" sub="Everyone in the A and B tabs, with where each stands." />
      <div className="toolbar">
        <form
          className="search"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            go({ q: words.trim() });
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
        <select value={filter.tier} onChange={(event) => go({ tier: event.target.value })} aria-label="Tier">
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
      </p>
      <div className="card flush scroll">
        <table className="leads-table">
          <thead>
            <tr>
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
            {rows.map((lead) => {
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
                  <td className="small">{lead.email}</td>
                  <td>
                    <div className="chips">
                      <Status tone={leadTone(lead.status)}>{lead.status_label}</Status>
                      {draft && <Status tone={draftTone(draft.status)}>Draft: {draft.status_label.toLowerCase()}</Status>}
                      {lead.ready && !draft && <Status tone="green">Ready</Status>}
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
            {rows.length === 0 && (
              <tr>
                <td colSpan={9} className="muted">
                  No lead matches.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </>
  );
}
