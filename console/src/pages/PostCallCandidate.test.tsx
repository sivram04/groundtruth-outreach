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

  it("renders nothing for a phone-only lead, an ineligible outcome, or a call stop", async () => {
    for (const reason of ["no_email", "outcome_not_eligible", "call_stop"]) {
      const { container } = render(
        <PostCallCandidate leadId="A-0002" load={load({ candidate: null, reason })} />,
      );
      await vi.waitFor(() => expect(container.querySelector(".card")).toBeNull());
      cleanup();
    }
  });

  it("preserves the founder's edits on a refresh that returns the same candidate, replaces on a changed one", async () => {
    const same = cand({ subject: "Tried to reach you — Lakshyaa" });
    const load = vi
      .fn()
      .mockResolvedValueOnce({ candidate: same })
      .mockResolvedValueOnce({ candidate: same }) // a refresh with the same basis
      .mockResolvedValue({ candidate: cand({ subject: "Following up after our call — Lakshyaa" }) });
    const { rerender } = render(<PostCallCandidate leadId="A-0002" reloadKey="1" load={load} />);
    await vi.waitFor(() => expect(screen.getByDisplayValue("Tried to reach you — Lakshyaa")).toBeTruthy());
    // the founder edits the subject
    fireEvent.change(screen.getByDisplayValue("Tried to reach you — Lakshyaa"), { target: { value: "My own subject" } });
    // a refresh with the SAME underlying candidate keeps the edit
    rerender(<PostCallCandidate leadId="A-0002" reloadKey="2" load={load} />);
    await vi.waitFor(() => expect(load).toHaveBeenCalledTimes(2));
    expect(screen.getByDisplayValue("My own subject")).toBeTruthy();
    // a refresh whose candidate changed replaces the edit
    rerender(<PostCallCandidate leadId="A-0002" reloadKey="3" load={load} />);
    await vi.waitFor(() => expect(screen.getByDisplayValue("Following up after our call — Lakshyaa")).toBeTruthy());
    expect(screen.queryByDisplayValue("My own subject")).toBeNull();
  });

  it("withdraws a stale candidate when the call state changes, and loads a new one", async () => {
    // A parent refresh (after a CallPanel save) changes reloadKey; the component must re-fetch, so an old
    // editable candidate is withdrawn on a later stop, and a new eligible call loads its own candidate.
    const first = cand({ subject: "Tried to reach you — Lakshyaa" });
    const load = vi
      .fn()
      .mockResolvedValueOnce({ candidate: first })
      .mockResolvedValueOnce({ candidate: null, reason: "call_stop" })
      .mockResolvedValue({ candidate: cand({ outcome: "INTERESTED", subject: "Following up after our call — Lakshyaa" }) });
    const { rerender } = render(<PostCallCandidate leadId="A-0002" reloadKey="1" load={load} />);
    await vi.waitFor(() => expect(screen.getByDisplayValue("Tried to reach you — Lakshyaa")).toBeTruthy());

    rerender(<PostCallCandidate leadId="A-0002" reloadKey="2" load={load} />);  // a later DO_NOT_CONTACT
    await vi.waitFor(() => expect(screen.queryByDisplayValue(/Tried to reach you/)).toBeNull());

    rerender(<PostCallCandidate leadId="A-0002" reloadKey="3" load={load} />);  // a new eligible call
    await vi.waitFor(() => expect(screen.getByDisplayValue("Following up after our call — Lakshyaa")).toBeTruthy());
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
