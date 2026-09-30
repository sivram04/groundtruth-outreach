import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { CallTask } from "../types";
import { CallPanel } from "./CallPanel";

afterEach(cleanup);

const DONE = { recorded: true, task: null, history: [], effect: "CONTINUE" };

function panel(over: Partial<Parameters<typeof CallPanel>[0]> = {}) {
  const record = vi.fn().mockResolvedValue(DONE);
  const act = vi.fn().mockResolvedValue(DONE);
  const onChanged = vi.fn();
  render(<CallPanel leadId="A-0001" phone="614-555-0142" task={null} history={[]} onChanged={onChanged}
                    record={record} act={act} {...over} />);
  return { record, act, onChanged };
}

describe("the call panel", () => {
  it("records a no-answer outcome and refreshes", async () => {
    const { record, onChanged } = panel();
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "rang out" } });
    fireEvent.click(screen.getByRole("button", { name: /Save call/ }));
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(record).toHaveBeenCalledWith("A-0001", { outcome: "NO_ANSWER", note: "rang out", callback_at: undefined });
  });

  it("requires an explicit time for a callback, then sends it", async () => {
    const { record } = panel();
    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "CALLBACK" } });
    fireEvent.click(screen.getByRole("button", { name: /Save call/ }));
    expect(screen.getByText(/callback needs an explicit date and time/)).toBeTruthy();
    expect(record).not.toHaveBeenCalled();  // nothing recorded from an ambiguous callback
    fireEvent.change(screen.getByLabelText("Callback at"), { target: { value: "2026-10-01T18:00" } });
    fireEvent.click(screen.getByRole("button", { name: /Save call/ }));
    await vi.waitFor(() => expect(record).toHaveBeenCalled());
    const [, body] = record.mock.calls[0]!;
    expect(body.outcome).toBe("CALLBACK");
    expect(typeof body.callback_at).toBe("string");  // an ISO instant, converted from the local time
  });

  it("shows an overdue task and completes / snoozes / cancels it", async () => {
    const task: CallTask = {
      status: "scheduled", outcome: "NO_ANSWER", why: "No answer", note: "rang out",
      due: "2026-10-01", due_kind: "DATE", due_text: "Thu 2026-10-01", overdue: true, snoozed: false,
      called_at: "2026-09-28 09:00 ET",
    };
    const { act, onChanged } = panel({ task });
    expect(screen.getByText("Overdue")).toBeTruthy();
    expect(screen.getByText(/Thu 2026-10-01/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /^Snooze/ }));
    fireEvent.change(screen.getByLabelText(/Snooze until/), { target: { value: "2026-10-09T14:00" } });
    fireEvent.click(screen.getByRole("button", { name: /Save snooze/ }));
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalledTimes(1));  // the action resolved (busy cleared)
    expect(act.mock.calls[0]![1].action).toBe("SNOOZE");
    expect(typeof act.mock.calls[0]![1].snooze_to).toBe("string");

    fireEvent.click(screen.getByRole("button", { name: /^Complete/ }));
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalledTimes(2));
    expect(act.mock.calls[1]![1]).toEqual({ action: "COMPLETE", snooze_to: undefined });
  });

  it("shows the email effect and call history", () => {
    panel({
      effectSaid: "Email stopped by the call outcome",
      history: [{ when: "2026-09-28 09:00 ET", what: "Do not contact", note: "asked to be removed" }],
    });
    expect(screen.getByText("Email stopped by the call outcome")).toBeTruthy();
    expect(screen.getAllByText("Do not contact").length).toBeGreaterThan(0);  // history + the select option
    expect(screen.getByText("asked to be removed")).toBeTruthy();
  });
});
