// The review flow for the demo build (no server): one made-up candidate, an in-memory decision.
// Nothing here is real; it lets the local demo show the confirm/reject flow and its states.
import type { ReviewView } from "../api";
import { ReviewStale } from "../api";

const CANDIDATE = {
  lead_id: "A-0007",
  to: "jo@lakeside-concrete.test",
  subject: "A conversation about a preview next week",
  body:
    "Hi Jo,\n\nLakeside Concrete pours foundations and slabs for commercial buildings.\n\n" +
    "I'm building a tool that helps construction subcontractors see their cash weeks ahead. " +
    "It is an early preview.\n\nWould you be open to a short conversation next week?\n\n" +
    "Best,\nDemo Founder\nFounder, Demo Product\nhttps://example.test\n" +
    '1 Made Up Road, Nowhere, OH 00000\nIf you don\'t want further outreach from me, reply "no thanks" and I\'ll stop.',
  claims: [
    { kind: "COMPANY", text: "Lakeside Concrete pours foundations and slabs for commercial buildings.", quote_id: "q1" },
    { kind: "PRODUCT", text: "I'm building a tool that helps construction subcontractors see their cash weeks ahead. It is an early preview.", quote_id: "" },
    { kind: "ASK", text: "Would you be open to a short conversation next week?", quote_id: "" },
  ],
  evidence: {
    category: "OFFERING",
    quote: "We pour foundations and slabs for commercial buildings.",
    url: "https://lakeside-concrete.test/services",
    quote_id: "q1",
  },
  handbook_hash: "demo-hash",
  handbook_version: "demo",
  fingerprint: "demofingerprint000000000000000000000000000000000000000000000000",
  note:
    "Confirming records your judgment that these claims are supported by the cited evidence. " +
    "It is not automated proof that they are true. Nothing is sent or drafted by confirming; " +
    "sending and drafting stay disabled.",
} satisfies Omit<ReviewView, "review">;

let decision: ReviewView["review"] = { decision: null, current: false };

export async function demoReview(_leadId: string): Promise<ReviewView> {
  return { ...structuredClone(CANDIDATE), review: { ...decision } };
}

export async function demoRecord(
  _leadId: string,
  choice: "confirm" | "reject",
  fingerprint: string,
): Promise<ReviewView> {
  if (fingerprint !== CANDIDATE.fingerprint) {
    throw new ReviewStale("The candidate changed since it was shown; reload and review it again.");
  }
  decision = {
    decision: choice === "confirm" ? "confirmed" : "rejected",
    reviewer: "demo@lakshyaa.ai",
    reviewed_at: new Date().toISOString(),
    current: true,
  };
  return { ...structuredClone(CANDIDATE), review: { ...decision } };
}
