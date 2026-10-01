import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ExperimentError } from "../api";
import type { ExperimentReport, Snapshot, VariantMetric } from "../types";
import { Experiments } from "./Experiments";

afterEach(cleanup);

function metrics(counts: Partial<Record<string, number>>): VariantMetric[] {
  const m = (key: string, label: string, count: number, denom: number, dlabel: string, extra = {}) =>
    ({ key, label, available: true, count, denominator: denom, denominator_label: dlabel, rate: denom ? `${Math.round((100 * count) / denom)}%` : "-", ...extra });
  const assigned = counts.assigned ?? 0;
  const sent = counts.sent ?? 0;
  return [
    m("assigned", "Assigned", assigned, assigned, "assigned"),
    m("drafted", "Drafted", counts.drafted ?? 0, assigned, "assigned"),
    m("sent", "Confirmed sent", sent, assigned, "assigned", { note: "a recorded send, not a confirmed delivery" }),
    m("replies", "Replies", counts.replies ?? 0, sent, "confirmed sent"),
    { key: "positive_replies", label: "Positive replies", available: false, why: "no positive-reply signal is recorded yet" },
    m("opt_outs", "Opt-outs", counts.opt_outs ?? 0, sent, "confirmed sent"),
    m("calls", "Calls made", counts.calls ?? 0, assigned, "assigned"),
    m("followups", "Follow-up emails sent", counts.followups ?? 0, sent, "confirmed sent"),
    { key: "meetings", label: "Meetings", available: false, why: "no meeting is recorded" },
    m("opens", "Opens", counts.opens ?? 0, counts.tracked ?? 0, "tracked sends", { estimate: true, note: "an estimate" }),
  ];
}

const REPORT: ExperimentReport = {
  name: "Subject test",
  defined: true,
  basis: "observed_activity",
  variants: [
    { index: 0, name: "Short", assigned: 3, suppressed: 0, excluded: { before_assignment: 1, undated: 0, unattributable: 1 }, lead_ids: ["A-0001"], metrics: metrics({ assigned: 3, sent: 2, replies: 1, opens: 1, tracked: 1 }) },
    { index: 1, name: "Long", assigned: 2, suppressed: 1, excluded: { before_assignment: 0, undated: 0, unattributable: 0 }, lead_ids: ["A-0002"], metrics: metrics({ assigned: 2, sent: 1, opt_outs: 1 }) },
  ],
  comparison: { winner: null, comparable: false, note: "This is observed activity by the assigned group, not A/B performance: the variant's content does not yet change any email and no exposure is recorded, so the two groups are not comparable." },
  notes: [
    "Observed activity by assigned group — not A/B performance.",
    "Only outcomes recorded at or after a lead was assigned are counted, and a downstream outcome counts only when it links to a send made after the lead was assigned.",
    "2 recorded event(s) are excluded: 1 happened before the lead was assigned, 1 could not be linked to a send made after assignment, and 0 could not be dated against the assignment.",
  ],
  excluded: { before_assignment: 1, undated: 0, unattributable: 1 },
  calls_unreadable: false,
  suppression_unreadable: false,
};

function snap(extra: Partial<Snapshot> = {}): Snapshot {
  return { experiments_enabled: true, experiments: REPORT, experiments_unreadable: false, ...extra } as unknown as Snapshot;
}

describe("the A/B tests page", () => {
  it("defines two variants and reports the result", async () => {
    const define = vi.fn().mockResolvedValue({ recorded: true, name: "Subject test", variants: ["Short", "Long"], written: 2 });
    const onChanged = vi.fn();
    render(<Experiments data={snap({ experiments: null })} onChanged={onChanged} define={define} assign={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Experiment/), { target: { value: " Subject test " } });
    fireEvent.change(screen.getByLabelText(/Variant A/), { target: { value: "Short" } });
    fireEvent.change(screen.getByLabelText(/Variant B/), { target: { value: "Long" } });
    fireEvent.click(screen.getByRole("button", { name: /Save the variants/ }));
    await vi.waitFor(() => expect(screen.getByText(/Saved .Subject test./)).toBeTruthy());
    // The name is trimmed before it is sent.
    expect(define).toHaveBeenCalledWith({ experiment: "Subject test", variant_a: "Short", variant_b: "Long" });
    expect(onChanged).toHaveBeenCalled();
  });

  it("will not define two variants with the same name", () => {
    render(<Experiments data={snap({ experiments: null })} define={vi.fn()} assign={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Experiment/), { target: { value: "E" } });
    fireEvent.change(screen.getByLabelText(/Variant A/), { target: { value: "Same" } });
    fireEvent.change(screen.getByLabelText(/Variant B/), { target: { value: "Same" } });
    expect((screen.getByRole("button", { name: /Save the variants/ }) as HTMLButtonElement).disabled).toBe(true);
  });

  it("assigns eligible leads and shows what happened", async () => {
    const assign = vi.fn().mockResolvedValue({ recorded: true, name: "Subject test", assigned: 3, already_assigned: 0, eligible: 3, ineligible: 2 });
    render(<Experiments data={snap()} onChanged={vi.fn()} define={vi.fn()} assign={assign} />);
    fireEvent.click(screen.getByRole("button", { name: /Assign eligible leads/ }));
    await vi.waitFor(() => expect(screen.getByText(/3 newly assigned/)).toBeTruthy());
    expect(assign).toHaveBeenCalledWith({ experiment: "Subject test" });
    expect(screen.getByText(/2 not eligible/)).toBeTruthy();
  });

  it("frames the report as observed activity, not A/B performance, and never a winner", () => {
    render(<Experiments data={snap()} define={vi.fn()} assign={vi.fn()} />);
    expect(screen.getByText("Observed activity by assigned group")).toBeTruthy();
    expect(screen.getByText("Not A/B performance")).toBeTruthy();
    expect(screen.getByText(/not comparable/)).toBeTruthy();
    expect(screen.getByText(/does not yet change any email/)).toBeTruthy();
    expect(screen.getAllByText("Short").length).toBeGreaterThan(0);
    expect(screen.getByText("Long")).toBeTruthy();
    // Positive replies and meetings have no recorded signal, so they read "not available", not 0.
    expect(screen.getAllByText("not available").length).toBeGreaterThanOrEqual(2);
    // Opens are labelled an estimate.
    expect(screen.getAllByText(/\(est\.\)/).length).toBeGreaterThan(0);
    // The suppressed-but-assigned context row.
    expect(screen.getByText(/Assigned, now suppressed/)).toBeTruthy();
    // Unattributable and pre-assignment outcomes are excluded and said so, not counted.
    expect(screen.getByText(/could not be linked to a send made after assignment/)).toBeTruthy();
  });

  it("shows the calls metric as not available when the Call log cannot be read", () => {
    const unavailableCalls: ExperimentReport = {
      ...REPORT,
      calls_unreadable: true,
      variants: REPORT.variants.map((v) => ({
        ...v,
        metrics: v.metrics.map((m) => (m.key === "calls" ? { key: "calls", label: "Calls made", available: false, why: "the Call log could not be read" } : m)),
      })),
    };
    render(<Experiments data={snap({ experiments: unavailableCalls })} define={vi.fn()} assign={vi.fn()} />);
    // positive replies (×2) + meetings (×2) + calls (×2) now read "not available".
    expect(screen.getAllByText("not available").length).toBeGreaterThanOrEqual(6);
  });

  it("shows the server's message when a define is refused", async () => {
    const define = vi.fn().mockRejectedValue(new ExperimentError("the two variants need different names"));
    render(<Experiments data={snap({ experiments: null })} define={define} assign={vi.fn()} />);
    fireEvent.change(screen.getByLabelText(/Experiment/), { target: { value: "E" } });
    fireEvent.change(screen.getByLabelText(/Variant A/), { target: { value: "A" } });
    fireEvent.change(screen.getByLabelText(/Variant B/), { target: { value: "B" } });
    fireEvent.click(screen.getByRole("button", { name: /Save the variants/ }));
    await vi.waitFor(() => expect(screen.getByText(/need different names/)).toBeTruthy());
  });

  it("says when the A/B tab could not be read", () => {
    render(<Experiments data={snap({ experiments: null, experiments_unreadable: true })} define={vi.fn()} assign={vi.fn()} />);
    expect(screen.getByText(/could not be read/)).toBeTruthy();
  });
});
