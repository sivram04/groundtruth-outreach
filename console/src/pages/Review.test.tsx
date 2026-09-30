import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  LoadError,
  ReviewStale,
  ReviewStatusUnavailable,
  loadReview,
  recordReview,
  type ReviewView,
} from "../api";
import { Review } from "./Review";

const FP = "f".repeat(64);

// A JSON Response for the real API parser (reviewResponse). This lets
// the tests exercise the actual server response shape through loadReview/recordReview, not just a
// resolved ReviewView or a thrown exception.
function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status, headers: { "Content-Type": "application/json" },
  });
}

// Returns each scripted response in call order (GET, POST, GET, ... in these flows), holding the last.
function fetchSequence(...responses: Response[]): typeof fetch {
  let i = 0;
  return vi.fn(async (): Promise<Response> => responses[Math.min(i++, responses.length - 1)]!) as unknown as typeof fetch;
}

const disabled = (name: RegExp) =>
  (screen.getByRole("button", { name }) as HTMLButtonElement).disabled;

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
    review: { decision: null, current: false, state: "REVIEW_MISSING" },
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
      .mockResolvedValue(view({ review: { decision: "confirmed", reviewer: "admin@lakshyaa.ai", current: true, state: "resolved" } }));
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={() => Promise.resolve(view())} record={record} />);
    await screen.findAllByText(/pours slabs/);
    fireEvent.click(screen.getByRole("button", { name: /Confirm/ }));
    await screen.findAllByText(/Confirmed by admin@lakshyaa.ai/);
    expect(record).toHaveBeenCalledWith("A-0007", "confirm", FP);
  });

  it("records a rejection", async () => {
    const record = vi
      .fn()
      .mockResolvedValue(view({ review: { decision: "rejected", reviewer: "admin@lakshyaa.ai", current: true, state: "resolved" } }));
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={() => Promise.resolve(view())} record={record} />);
    await screen.findAllByText(/pours slabs/);
    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
    await screen.findAllByText(/Rejected by admin@lakshyaa.ai/);
    expect(record).toHaveBeenCalledWith("A-0007", "reject", FP);
  });

  it("shows a stale state when a review no longer matches the candidate", async () => {
    const stale = view({ review: { decision: "confirmed", reviewer: "admin@lakshyaa.ai", current: false, state: "resolved" } });
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

  it("says the review was recorded but its status could not be loaded, without showing approval", async () => {
    const record = vi
      .fn()
      .mockRejectedValueOnce(
        new ReviewStatusUnavailable("Your review was recorded, but its current status could not be loaded. Reload before continuing."),
      );
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={() => Promise.resolve(view())} record={record} />);
    await screen.findAllByText(/pours slabs/);
    fireEvent.click(screen.getByRole("button", { name: /Confirm/ }));
    await screen.findByText(/recorded, but its current status could not be loaded/);
    // it must NOT show current approval
    expect(screen.queryByText(/Confirmed by/)).toBeNull();
  });

  it("clears a stale confirmation when the status can't be read back, then a reload restores it", async () => {
    const confirmed = view({ review: { decision: "confirmed", reviewer: "admin@lakshyaa.ai", current: true, state: "resolved" } });
    const rejected = view({ review: { decision: "rejected", reviewer: "admin@lakshyaa.ai", current: true, state: "resolved" } });
    const load = vi.fn().mockResolvedValueOnce(confirmed).mockResolvedValueOnce(rejected);
    const record = vi
      .fn()
      .mockRejectedValueOnce(
        new ReviewStatusUnavailable("Your review was recorded, but its current status could not be loaded. Reload before continuing."),
      );
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={load} record={record} />);
    await screen.findAllByText(/Confirmed by admin/);  // starts from a current confirmed review

    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
    await screen.findAllByText(/could not be loaded/);
    // the stale confirmation is gone; the status is unavailable; actions are disabled; candidate kept
    expect(screen.queryByText(/Confirmed by/)).toBeNull();
    expect(screen.getAllByText(/Current status unavailable/).length).toBeGreaterThan(0);
    expect((screen.getByRole("button", { name: /Confirm/ }) as HTMLButtonElement).disabled).toBe(true);
    expect((screen.getByRole("button", { name: /Reject/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getAllByText(/pours slabs/).length).toBeGreaterThan(0);  // evidence preserved

    // a successful reload restores the correct decision and re-enables actions
    fireEvent.click(screen.getByRole("button", { name: /Reload/ }));
    await screen.findAllByText(/Rejected by admin/);
    expect(screen.queryByText(/Current status unavailable/)).toBeNull();
    expect((screen.getByRole("button", { name: /Confirm/ }) as HTMLButtonElement).disabled).toBe(false);
  });

  it("says plainly when there is no candidate to review", async () => {
    render(<Review leadId="A-9999" from="admin@lakshyaa.ai" load={() => Promise.reject(new LoadError("There is no candidate to review for this lead."))} record={vi.fn()} />);
    await screen.findByText(/no candidate to review/);
  });

  // The API/UI mismatch this covers: a successful (HTTP 200) load whose resolved chain state is a
  // failed/invalid history must keep the actions disabled. HTTP success does not establish a usable
  // decision. These drive the real parser (loadReview/recordReview) with the actual server JSON.
  it("keeps actions disabled after a save whose status can't be read back, through reload, until a clean decision returns", async () => {
    const fetcher = fetchSequence(
      // GET #1: a current confirmed review
      jsonResponse(view({ review: { decision: "confirmed", reviewer: "admin@lakshyaa.ai", current: true, state: "resolved" } })),
      // POST reject: saved, but the status could not be read back (HTTP 200 recorded/status_unavailable)
      jsonResponse({ recorded: true, status_unavailable: true, message: "Your review was recorded, but its current status could not be loaded. Reload before continuing." }),
      // GET #2 (reload): HTTP 200 but the history is unreadable — NOT a usable decision
      jsonResponse(view({ review: { decision: null, current: false, state: "unreadable" } })),
      // GET #3 (reload): the resolved rejection
      jsonResponse(view({ review: { decision: "rejected", reviewer: "admin@lakshyaa.ai", current: true, state: "resolved" } })),
    );
    render(
      <Review
        leadId="A-0007"
        from="admin@lakshyaa.ai"
        load={(id) => loadReview(id, fetcher)}
        record={(id, d, fp) => recordReview(id, d, fp, fetcher)}
      />,
    );
    await screen.findAllByText(/Confirmed by admin/);

    // save fails to read back → recorded-but-unavailable, actions disabled
    fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
    await screen.findAllByText(/recorded, but its current status could not be loaded/);
    expect(screen.queryByText(/Confirmed by/)).toBeNull();
    expect(disabled(/Confirm/)).toBe(true);
    expect(disabled(/Reject/)).toBe(true);

    // reload returns HTTP 200 with an unreadable state → actions REMAIN disabled (the bug being fixed)
    fireEvent.click(screen.getByRole("button", { name: /Reload/ }));
    await screen.findByText(/review history could not be read/);
    expect(screen.queryByText(/Awaiting your review/)).toBeNull();
    expect(disabled(/Confirm/)).toBe(true);
    expect(disabled(/Reject/)).toBe(true);
    expect(screen.getAllByText(/pours slabs/).length).toBeGreaterThan(0);  // candidate/evidence preserved

    // a later reload returns the resolved rejection → correct status and actions restored
    fireEvent.click(screen.getByRole("button", { name: /Reload/ }));
    await screen.findAllByText(/Rejected by admin/);
    expect(disabled(/Confirm/)).toBe(false);
    expect(disabled(/Reject/)).toBe(false);
  });

  it("blocks review on an unverifiable history on the initial load (verification not configured)", async () => {
    const fetcher = fetchSequence(
      jsonResponse(view({ review: { decision: null, current: false, state: "unverifiable" } })),
    );
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={(id) => loadReview(id, fetcher)} record={vi.fn()} />);
    await screen.findByText(/verification is not configured/);
    expect(screen.queryByText(/Awaiting your review/)).toBeNull();
    expect(disabled(/Confirm/)).toBe(true);
    expect(disabled(/Reject/)).toBe(true);
    expect(screen.getByRole("button", { name: /Reload/ })).toBeTruthy();
    expect(screen.getAllByText(/pours slabs/).length).toBeGreaterThan(0);
  });

  it("blocks review on a conflicting history on the initial load", async () => {
    const fetcher = fetchSequence(
      jsonResponse(view({ review: { decision: null, current: false, state: "REVIEW_CONFLICT" } })),
    );
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={(id) => loadReview(id, fetcher)} record={vi.fn()} />);
    await screen.findAllByText(/decisions conflict/);
    expect(screen.queryByText(/Awaiting your review/)).toBeNull();
    expect(disabled(/Confirm/)).toBe(true);
    expect(disabled(/Reject/)).toBe(true);
  });

  it("blocks review on a tampered history on the initial load", async () => {
    const fetcher = fetchSequence(
      jsonResponse(view({ review: { decision: null, current: false, state: "REVIEW_TAMPERED" } })),
    );
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={(id) => loadReview(id, fetcher)} record={vi.fn()} />);
    await screen.findAllByText(/could not be verified/);
    expect(screen.queryByText(/Awaiting your review/)).toBeNull();
    expect(disabled(/Confirm/)).toBe(true);
    expect(disabled(/Reject/)).toBe(true);
  });

  it("permits review on a genuine REVIEW_MISSING (no record yet), distinct from a failed history", async () => {
    const fetcher = fetchSequence(
      jsonResponse(view({ review: { decision: null, current: false, state: "REVIEW_MISSING" } })),
    );
    render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={(id) => loadReview(id, fetcher)} record={vi.fn()} />);
    await screen.findAllByText(/Awaiting your review/);
    expect(disabled(/Confirm/)).toBe(false);
    expect(disabled(/Reject/)).toBe(false);
  });

  it.each([undefined, null, "UNKNOWN_STATE", "unreadable"])(
    "blocks an initial HTTP 200 with unusable state %s, preserving candidate and evidence",
    async (state) => {
      const fetcher = fetchSequence(jsonResponse({
        ...view(), review: { decision: null, current: false, state },
      }));
      const record = vi.fn();
      render(<Review leadId="A-0007" from="admin@lakshyaa.ai" load={(id) => loadReview(id, fetcher)} record={record} />);
      await screen.findByText(/reviewing is paused/i);
      expect(screen.queryByText(/Awaiting your review/)).toBeNull();
      expect(disabled(/Confirm/)).toBe(true);
      expect(disabled(/Reject/)).toBe(true);
      expect(screen.getByRole("button", { name: /Reload/ })).toBeTruthy();
      expect(screen.getByText("A conversation next week")).toBeTruthy();
      expect(screen.getByText(/We pour foundations and slabs/)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: /Confirm/ }));
      fireEvent.click(screen.getByRole("button", { name: /Reject/ }));
      expect(record).not.toHaveBeenCalled();
    },
  );
});
