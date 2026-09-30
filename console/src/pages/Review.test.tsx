import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LoadError, ReviewStale, type ReviewView } from "../api";
import { Review } from "./Review";

const FP = "f".repeat(64);

function view(over: Partial<ReviewView> = {}): ReviewView {
  return {
    lead_id: "A-0007",
    to: "jo@lakeside-concrete.test",
    subject: "A conversation next week",
    body: "Hi Jo,\n\nLakeside Concrete pours slabs for commercial buildings.",
    claims: [{ kind: "COMPANY", text: "Lakeside Concrete pours slabs for commercial buildings.", quote_id: "q1" }],
    evidence: { category: "OFFERING", quote: "We pour foundations and slabs.", url: "https://lakeside-concrete.test/s", quote_id: "q1" },
    handbook_hash: "h",
    handbook_version: "1",
    fingerprint: FP,
    review: { decision: null, current: false },
    note: "Confirming records your judgment... It is not automated proof that they are true.",
    ...over,
  };
}

afterEach(cleanup);

describe("the review page", () => {
  it("shows the recipient, subject, body and cited evidence, pending review", async () => {
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={() => Promise.resolve(view())} record={vi.fn()} />);
    await screen.findAllByText(/pours slabs for commercial buildings/);
    expect(screen.getByText("jo@lakeside-concrete.test")).toBeTruthy();
    expect(screen.getByText("A conversation next week")).toBeTruthy();
    expect(screen.getByText(/We pour foundations and slabs/)).toBeTruthy();
    expect(screen.getAllByText(/Awaiting your review/).length).toBeGreaterThan(0);
    // sending and drafting are disabled, and confirming is not called proof
    expect(screen.getByText(/sending and drafting stay disabled/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /send/i })).toBeNull();
  });

  it("confirms with the candidate's fingerprint and shows who confirmed it", async () => {
    const record = vi
      .fn()
      .mockResolvedValue(view({ review: { decision: "confirmed", reviewer: "admin@lakshyaa.ai", current: true } }));
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={() => Promise.resolve(view())} record={record} />);
    await screen.findAllByText(/pours slabs/);
    fireEvent.click(screen.getByRole("button", { name: /Confirm/ }));
    await screen.findAllByText(/Confirmed by admin@lakshyaa.ai/);
    expect(record).toHaveBeenCalledWith("A-0007", "confirm", FP);
  });

  it("records a rejection", async () => {
    const record = vi
      .fn()
      .mockResolvedValue(view({ review: { decision: "rejected", reviewer: "admin@lakshyaa.ai", current: true } }));
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={() => Promise.resolve(view())} record={record} />);
    await screen.findAllByText(/pours slabs/);
    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
    await screen.findAllByText(/Rejected by admin@lakshyaa.ai/);
    expect(record).toHaveBeenCalledWith("A-0007", "reject", FP);
  });

  it("shows a stale state when a review no longer matches the candidate", async () => {
    const stale = view({ review: { decision: "confirmed", reviewer: "admin@lakshyaa.ai", current: false } });
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={() => Promise.resolve(stale)} record={vi.fn()} />);
    await screen.findAllByText(/no longer matches this candidate/);
  });

  it("refuses an edit made between display and confirmation, then reloads the changed candidate", async () => {
    const load = vi
      .fn()
      .mockResolvedValueOnce(view())
      .mockResolvedValueOnce(view({ subject: "An edited subject after review" }));
    const record = vi.fn().mockRejectedValueOnce(new ReviewStale("The candidate changed since it was shown; reload and review it again."));
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={load} record={record} />);
    await screen.findByText("A conversation next week");
    fireEvent.click(screen.getByRole("button", { name: /Confirm/ }));
    await screen.findByText(/changed since it was shown/);
    // it reloaded the current candidate so it can be reviewed afresh
    await screen.findByText("An edited subject after review");
    expect(load).toHaveBeenCalledTimes(2);
  });

  it("says plainly when there is no candidate to review", async () => {
    render(<Review leadId="A-9999" from="admin@lakshyaa.ai" load={() => Promise.reject(new LoadError("There is no candidate to review for this lead."))} record={vi.fn()} />);
    await screen.findByText(/no candidate to review/);
  });
});
