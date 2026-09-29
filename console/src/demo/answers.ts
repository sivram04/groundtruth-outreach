import type { Answer } from "../api";
import demo from "./snapshot.json";
import type { Snapshot } from "../types";

// The demo build has no server and no model, so the assistant is answered from the made-up
// leads themselves. The real app never uses this file.
const data = demo as unknown as Snapshot;

export async function demoAnswer(question: string): Promise<Answer> {
  await new Promise((wake) => setTimeout(wake, 450));
  const asked = question.toLowerCase();
  if (/send|approve|reply to|write to|delete|change/.test(asked)) {
    return {
      answer:
        "I only read your Sheet, so I cannot send or change anything. The drafts are on the " +
        "Drafts page, and approving one to send comes in a later version.",
      refused: false,
      link: { page: "drafts", lead_id: "", show: "", label: "Open the drafts" },
    };
  }
  if (asked.includes("draft")) {
    const waiting = data.drafts_summary.waiting;
    return {
      answer:
        `${data.drafts.length} first emails are written. ${waiting} wait only for your approval of the ` +
        `offer wording, and ${data.drafts_summary.held} ${data.drafts_summary.held === 1 ? "is" : "are"} held by the writing checks.`,
      refused: false,
      lead_ids: data.drafts.map((draft) => draft.lead_id),
      link: { page: "drafts", lead_id: "", show: "", label: "Read them" },
    };
  }
  if (asked.includes("repl")) {
    const replied = data.leads.filter((lead) => lead.status === "REPLIED");
    return {
      answer: replied.length
        ? `${replied[0]!.company} replied. Nobody else has.`
        : "Nobody has replied yet.",
      refused: false,
      lead_ids: replied.map((lead) => lead.id),
      link: { page: "leads", lead_id: "", show: "replied", label: "See the replies" },
    };
  }
  const first = data.needs_you[0];
  return {
    answer: first
      ? `${data.needs_you.length} things need you. The first is ${data.leads.find((lead) => lead.id === first.lead_id)?.company}: ${first.text}`
      : "Nothing needs you right now.",
    refused: false,
    lead_ids: data.needs_you.map((item) => item.lead_id),
    link: { page: "leads", lead_id: "", show: "needs", label: "See what needs you" },
  };
}
