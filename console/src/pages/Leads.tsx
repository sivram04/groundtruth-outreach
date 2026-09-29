import { useState } from "react";
import { Pill } from "../components";
import { SHOW, filterLeads, readFilter, type LeadFilter } from "../filters";
import { href, leadHref } from "../router";
import type { Snapshot } from "../types";

export function Leads({ data, query }: { data: Snapshot; query: URLSearchParams }) {
  const filter = readFilter(query, data);
  const [words, setWords] = useState(filter.q);
  const rows = filterLeads(data, filter);
  const go = (changes: Partial<LeadFilter>) => {
    const next = { ...filter, ...changes };
    window.location.hash = href("/leads", { q: next.q, tier: next.tier, show: next.show === "all" ? "" : next.show });
  };
  return (
    <>
      <h1>Leads</h1>
      <form
        className="filters"
        role="search"
        onSubmit={(event) => {
          event.preventDefault();
          go({ q: words.trim() });
        }}
      >
        <input
          type="search"
          value={words}
          onChange={(event) => setWords(event.target.value)}
          placeholder="Company, contact or email"
          aria-label="Search leads"
          maxLength={100}
        />
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
        <select value={filter.show} onChange={(event) => go({ show: event.target.value })} aria-label="Show">
          {SHOW.map(([key, label]) => (
            <option key={key} value={key}>
              {label}
            </option>
          ))}
        </select>
        <button type="submit">Search</button>
      </form>
      <p className="muted small" aria-live="polite">
        {rows.length} of {data.leads.length} leads
      </p>
      <div className="card flush scroll">
        <table>
          <thead>
            <tr>
              <th scope="col">Lead</th>
              <th scope="col">Company</th>
              <th scope="col">Contact</th>
              <th scope="col">Email</th>
              <th scope="col">Check</th>
              <th scope="col">Fit</th>
              <th scope="col">Status</th>
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
            {rows.map((lead) => (
              <tr key={lead.id}>
                <td className="nowrap">
                  <a href={leadHref(lead.id)}>{lead.id}</a>
                </td>
                <td>{lead.company}</td>
                <td>{lead.contact}</td>
                <td>{lead.email}</td>
                <td>{lead.email_check}</td>
                <td>{lead.fit}</td>
                <td>
                  <Pill tone={lead.status}>{lead.status_label}</Pill>
                  {lead.ready && (
                    <>
                      {" "}
                      <Pill tone="ok">Ready</Pill>
                    </>
                  )}
                </td>
                <td className="nowrap">{lead.cells["Sent at"] ?? ""}</td>
                <td className="num">{lead.cells["Follow-ups sent"] ?? ""}</td>
                <td className="num">{lead.cells["Opens (est.)"] ?? ""}</td>
                <td className="num">{lead.cells["Clicks"] ?? ""}</td>
                <td className="small">{lead.action}</td>
              </tr>
            ))}
            {rows.length === 0 && (
              <tr>
                <td colSpan={12} className="muted">
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
