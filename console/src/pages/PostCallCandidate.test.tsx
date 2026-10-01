import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CallCandidate, CallCandidateResult } from "../types";
import { PostCallCandidate } from "./PostCallCandidate";

afterEach(cleanup);

function cand(over: Partial<CallCandidate> = {}): CallCandidate {
  return {
    outcome: "NO_ANSWER", to: "sam@example.test", subject: "Tried to reach you — Lakshyaa",
    body: "Hi there,\n\nI tried to reach you by phone today but could not get through.\n\n…",
    evidence: { quote: "We install electrical systems.", url: "https://example.test/x" },
    note: "rang out", callback_at: "", callback_text: "", handbook_hash: "h1abc234", handbook_name: "Handbook",
    ...over,
  };
}

const load = (result: CallCandidateResult) => () => Promise.resolve(result);

describe("the post-call candidate", () => {
  it("shows the candidate, its evidence and a discard action", async () => {
    render(<PostCallCandidate leadId="A-0001" load={load({ candidate: cand() })} />);
    await vi.waitFor(() => expect(screen.getByDisplayValue("Tried to reach you — Lakshyaa")).toBeTruthy());
    expect(screen.getByText(/not sent and creates no Gmail draft/)).toBeTruthy();
    expect(screen.getByText(/We install electrical systems/)).toBeTruthy();  // the cited evidence
    expect(screen.getByText("rang out")).toBeTruthy();  // the note as context
    fireEvent.click(screen.getByRole("button", { name: /Discard/ }));
    expect(screen.getByText(/Discarded/)).toBeTruthy();
    expect(screen.queryByDisplayValue(/Tried to reach you/)).toBeNull();
  });

  it("renders nothing for a phone-only lead or an ineligible outcome", async () => {
    const { container } = render(
      <PostCallCandidate leadId="A-0001" load={load({ candidate: null, reason: "no_email" })} />,
    );
    await vi.waitFor(() => expect(container.querySelector(".card")).toBeNull());
    cleanup();
    const other = render(
      <PostCallCandidate leadId="A-0002" load={load({ candidate: null, reason: "outcome_not_eligible" })} />,
    );
    await vi.waitFor(() => expect(other.container.querySelector(".card")).toBeNull());
  });

  it("explains a suppressed lead rather than offering an email", async () => {
    render(<PostCallCandidate leadId="A-0002" load={load({ candidate: null, reason: "suppressed" })} />);
    await vi.waitFor(() => expect(screen.getByText(/opted out/)).toBeTruthy());
  });

  it("shows an unavailable state when a source could not be read", async () => {
    render(
      <PostCallCandidate
        leadId="A-0002"
        load={load({ candidate: null, unavailable: true, reason: "suppression_unreadable" })}
      />,
    );
    await vi.waitFor(() => expect(screen.getByText(/unavailable right now/)).toBeTruthy());
  });

  it("shows the recorded callback time when present", async () => {
    render(
      <PostCallCandidate
        leadId="A-0002"
        load={load({ candidate: cand({ outcome: "CALLBACK", callback_text: "2026-10-02 14:00 ET" }) })}
      />,
    );
    await vi.waitFor(() => expect(screen.getByText("2026-10-02 14:00 ET")).toBeTruthy());
  });
});
