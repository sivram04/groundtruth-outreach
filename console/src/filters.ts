import type { Lead, Snapshot } from "./types";

// The Leads page's filters. Each keeps a lead or not; they narrow the list and change nothing.

export const SHOW: [string, string][] = [
  ["all", "All leads"],
  ["needs", "Needs you"],
  ["ready", "Ready for a first draft"],
  ["emailed", "Emailed"],
  ["not-emailed", "Not emailed"],
  ["replied", "Replied"],
  ["stopped", "Asked to stop"],
  ["bounced", "Bounced"],
  ["check", "Match to check"],
];

export interface LeadFilter {
  q: string;
  tier: string;
  show: string;
}

export function readFilter(query: URLSearchParams, data: Snapshot): LeadFilter {
  const show = query.get("show") ?? "all";
  const tier = query.get("tier") ?? "";
  const tiers = new Set(data.tiers.map((t) => t.prefix).filter(Boolean));
  return {
    q: (query.get("q") ?? "").slice(0, 100),
    tier: tiers.has(tier) ? tier : "",
    show: SHOW.some(([key]) => key === show) ? show : "all",
  };
}

function shown(lead: Lead, show: string, needs: Set<string>): boolean {
  switch (show) {
    case "needs":
      return needs.has(lead.id);
    case "ready":
      return lead.ready;
    case "emailed":
      return Boolean(lead.cells["Sent at"]);
    case "not-emailed":
      return !lead.cells["Sent at"] && !lead.error;
    case "replied":
      return lead.status === "REPLIED";
    case "stopped":
      return lead.status === "OPTED_OUT";
    case "bounced":
      return lead.status === "BOUNCED";
    case "check":
      return lead.status === "REVIEW_NEEDED";
    default:
      return true;
  }
}

export function filterLeads(data: Snapshot, filter: LeadFilter): Lead[] {
  const needs = new Set(data.needs_you.map((item) => item.lead_id));
  const words = filter.q.trim().toLowerCase();
  return data.leads.filter(
    (lead) =>
      shown(lead, filter.show, needs) &&
      (!filter.tier || lead.tier === filter.tier) &&
      (!words ||
        [lead.id, lead.company, lead.contact, lead.email].some((value) => value.toLowerCase().includes(words))),
  );
}
