import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CallError, recordCallOutcome } from "../api";
import type { CallTask } from "../types";
import { CallPanel } from "./CallPanel";

afterEach(cleanup);

const DONE = { recorded: true, task: null, history: [], effect: "CONTINUE" };

const SCHEDULED: CallTask = {
  id: "T1", status: "scheduled", outcome: "NO_ANSWER", why: "No answer", note: "rang out",
  due: "2026-10-01", due_kind: "DATE", due_text: "Thu 2026-10-01", overdue: true, snoozed: false,
  called_at: "2026-09-28 09:00 ET",
};

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
    const [, body] = record.mock.calls[0]!;
    expect(body.outcome).toBe("NO_ANSWER");
    expect(body.note).toBe("rang out");
    expect(body.callback_at).toBeUndefined();
    expect(typeof body.submission_id).toBe("string");  // one logical submission's identity
  });

  it("keeps one submission identity across a retry, and a new call gets a new one", async () => {
    // The UI omits the call time, so without a stable identity each retry would be a new server-stamped
    // event (finding 4). A retry of the same call must reuse the identity; a genuinely new call must not.
    const record = vi
      .fn()
      .mockRejectedValueOnce(new CallError("The call could not be recorded."))
      .mockResolvedValue(DONE);
    const onChanged = vi.fn();
    render(<CallPanel leadId="A-0001" phone="" task={null} onChanged={onChanged} record={record} act={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "rang out" } });
    fireEvent.click(screen.getByRole("button", { name: /Save call/ }));
    await vi.waitFor(() => expect(screen.getByText("The call could not be recorded.")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Save call/ }));  // retry, unchanged
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    const first = record.mock.calls[0]![1].submission_id;
    expect(record.mock.calls[1]![1].submission_id).toBe(first);  // a retry is one submission

    fireEvent.change(screen.getByLabelText("Note"), { target: { value: "left a message" } });
    fireEvent.click(screen.getByRole("button", { name: /Save call/ }));
    await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(3));
    expect(record.mock.calls[2]![1].submission_id).not.toBe(first);  // a new call, a new identity
  });

  it("names the exact task in a task action, so a stale action cannot close a newer one", async () => {
    const { act, onChanged } = panel({ task: { ...SCHEDULED, id: "T2" } });
    fireEvent.click(screen.getByRole("button", { name: /^Complete/ }));
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(act.mock.calls[0]![1].task_id).toBe("T2");
  });

  it("shows a partial-success warning and retries the rest with the same submission id", async () => {
    // A recorded call whose suppression entry failed: say what succeeded and what remains, and let the
    // founder retry WITHOUT recording a second call (the same submission id is idempotent).
    const record = vi
      .fn()
      .mockResolvedValueOnce({
        recorded: true, task: null, history: [], effect: "STOP", suppression_written: false,
        warning: "The email suppression list may be incomplete until you retry.",
      })
      .mockResolvedValue({ recorded: true, task: null, history: [], effect: "STOP", suppression_written: true });
    const onChanged = vi.fn();
    render(<CallPanel leadId="A-0002" phone="" task={null} onChanged={onChanged} record={record} act={vi.fn()} />);
    fireEvent.change(screen.getByLabelText("Outcome"), { target: { value: "DO_NOT_CONTACT" } });
    fireEvent.click(screen.getByRole("button", { name: /Save call/ }));
    await vi.waitFor(() => expect(screen.getByText(/suppression list may be incomplete/)).toBeTruthy());
    expect(screen.getByText(/The call was saved/)).toBeTruthy();
    expect(onChanged).toHaveBeenCalled();  // the call itself did record, so the view refreshed
    const firstId = record.mock.calls[0]![1].submission_id;

    fireEvent.click(screen.getByRole("button", { name: /Retry the rest/ }));
    await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(2));
    expect(record.mock.calls[1]![1].submission_id).toBe(firstId);  // one call, retried - not a new one
    await vi.waitFor(() => expect(screen.queryByText(/suppression list may be incomplete/)).toBeNull());
  });

  it("parses the real partial-success response shape", async () => {
    // Exercise the actual API parser, not only an injected mock: the server's partial JSON round-trips.
    const fetcher = (async () =>
      new Response(
        JSON.stringify({ recorded: true, task: null, history: [], effect: "STOP", suppression_written: false, warning: "not written" }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      )) as unknown as typeof fetch;
    const result = await recordCallOutcome("A-0002", { outcome: "DO_NOT_CONTACT", submission_id: "s-1" }, fetcher);
    expect(result.recorded).toBe(true);
    expect(result.suppression_written).toBe(false);
    expect(result.warning).toBe("not written");
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
    const { act, onChanged } = panel({ task: SCHEDULED });
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
    expect(act.mock.calls[1]![1]).toEqual({ action: "COMPLETE", snooze_to: undefined, task_id: "T1" });
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
