import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { ReplyCandidate as ReplyCand, ReplyCandidateResult } from "../types";
import { ReplyCandidate } from "./ReplyCandidate";

afterEach(cleanup);

function cand(over: Partial<ReplyCand> = {}): ReplyCand {
  return {
    to: "dana@bluebird.test",
    subject: "Re: Lakshyaa",
    body: "Hi Dana,\n\nThank you for getting back to me.\n\nWould next week work?\n\n…",
    booking_link: "",
    evidence: { quote: "We install electrical systems.", url: "https://example.test/x" },
    thread_id: "T1",
    in_reply_to: "r1",
    replied_at: "2026-09-27T10:00:00Z",
    handbook_hash: "h1abc234",
    handbook_name: "Handbook",
    ...over,
  };
}

const load = (result: ReplyCandidateResult) => () => Promise.resolve(result);

describe("the reply candidate", () => {
  it("shows the reply, its evidence and a discard action", async () => {
    render(<ReplyCandidate leadId="A-0002" load={load({ candidate: cand() })} />);
    await vi.waitFor(() => expect(screen.getByDisplayValue("Re: Lakshyaa")).toBeTruthy());
    expect(screen.getByText(/not sent and creates no Gmail draft/)).toBeTruthy();
    expect(screen.getByText(/does not repeat what their reply said/)).toBeTruthy();
    expect(screen.getByText(/We install electrical systems/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Discard/ }));
    expect(screen.getByText(/Discarded/)).toBeTruthy();
    expect(screen.queryByDisplayValue("Re: Lakshyaa")).toBeNull();
  });

  it("shows a configured booking link", async () => {
    const url = "https://cal.example/founder/intro";
    render(<ReplyCandidate leadId="A-0002" load={load({ candidate: cand({ booking_link: url }) })} />);
    await vi.waitFor(() => expect(screen.getByText(url)).toBeTruthy());
  });

  it("renders nothing when there is no reply yet or no email", async () => {
    for (const reason of ["no_reply", "no_email"]) {
      const { container } = render(
        <ReplyCandidate leadId="A-0002" load={load({ candidate: null, reason })} />,
      );
      await vi.waitFor(() => expect(container.querySelector(".card")).toBeNull());
      cleanup();
    }
  });

  it("explains a suppressed lead and a call stop rather than offering a reply", async () => {
    render(<ReplyCandidate leadId="A-0002" load={load({ candidate: null, reason: "suppressed" })} />);
    await vi.waitFor(() => expect(screen.getByText(/opted out/)).toBeTruthy());
    cleanup();
    render(<ReplyCandidate leadId="A-0002" load={load({ candidate: null, reason: "call_stop" })} />);
    await vi.waitFor(() => expect(screen.getByText(/stops contact/)).toBeTruthy());
  });

  it("shows an unavailable state when a source could not be read", async () => {
    render(
      <ReplyCandidate
        leadId="A-0002"
        load={load({ candidate: null, unavailable: true, reason: "call_log_unreadable" })}
      />,
    );
    await vi.waitFor(() => expect(screen.getByText(/unavailable right now/)).toBeTruthy());
  });

  it("preserves the founder's edits on a same-basis refresh, replaces on a changed one", async () => {
    const same = cand();
    const loader = vi
      .fn()
      .mockResolvedValueOnce({ candidate: same })
      .mockResolvedValueOnce({ candidate: same })
      .mockResolvedValue({ candidate: cand({ subject: "Re: Lakshyaa — following up" }) });
    const { rerender } = render(<ReplyCandidate leadId="A-0002" reloadKey="1" load={loader} />);
    await vi.waitFor(() => expect(screen.getByDisplayValue("Re: Lakshyaa")).toBeTruthy());
    fireEvent.change(screen.getByDisplayValue("Re: Lakshyaa"), { target: { value: "My own subject" } });
    rerender(<ReplyCandidate leadId="A-0002" reloadKey="2" load={loader} />);
    await vi.waitFor(() => expect(loader).toHaveBeenCalledTimes(2));
    expect(screen.getByDisplayValue("My own subject")).toBeTruthy();
    rerender(<ReplyCandidate leadId="A-0002" reloadKey="3" load={loader} />);
    await vi.waitFor(() => expect(screen.getByDisplayValue("Re: Lakshyaa — following up")).toBeTruthy());
    expect(screen.queryByDisplayValue("My own subject")).toBeNull();
  });
});
