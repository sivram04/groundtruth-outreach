import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CallError } from "../api";
import type { CallQueueItem } from "../types";
import { CallQueue } from "./CallQueue";

afterEach(cleanup);

function item(over: Partial<CallQueueItem> = {}): CallQueueItem {
  return {
    id: "T1", lead_id: "A-0001", company: "Redwood Plumbing", contact: "Sam Ford",
    phone: "614-555-0142", why: "No answer", note: "rang out", due: "2026-10-01",
    due_kind: "DATE", due_text: "Thu 2026-10-01", overdue: false, when: "TODAY",
    ...over,
  };
}

describe("the call queue", () => {
  it("lists overdue and due-today together and keeps upcoming separate", () => {
    const tasks = [
      item({ id: "T0", lead_id: "A-0002", company: "Bluebird", overdue: true, when: "OVERDUE" }),
      item({ id: "T1", lead_id: "A-0001", company: "Redwood", when: "TODAY" }),
      item({ id: "T2", lead_id: "A-0003", company: "Acme", when: "UPCOMING", due_text: "Mon 2026-10-06" }),
    ];
    render(<CallQueue tasks={tasks} onChanged={vi.fn()} act={vi.fn()} />);
    expect(screen.getByText("Overdue")).toBeTruthy();
    expect(screen.getByText("Due today")).toBeTruthy();
    expect(screen.getByText("1 overdue")).toBeTruthy();  // the header count
    expect(screen.getByText("1 upcoming")).toBeTruthy();  // upcoming is a separate section
    // the lead links point at each lead
    expect(screen.getByRole("link", { name: "Redwood" }).getAttribute("href")).toBe("#/leads/A-0001");
  });

  it("shows an unavailable state, not 'no calls due', when call history is unreadable", () => {
    render(<CallQueue tasks={[]} unreadable onChanged={vi.fn()} act={vi.fn()} />);
    expect(screen.getByText(/call log could not be read/)).toBeTruthy();
    expect(screen.queryByText(/No calls are due/)).toBeNull();
  });

  it("says there are no calls due only when the queue is genuinely empty", () => {
    render(<CallQueue tasks={[]} onChanged={vi.fn()} act={vi.fn()} />);
    expect(screen.getByText(/No calls are due/)).toBeTruthy();
  });

  it("completes a call by its exact task id and refreshes", async () => {
    const act = vi.fn().mockResolvedValue({ recorded: true, task: null, history: [], effect: "CONTINUE" });
    const onChanged = vi.fn();
    render(<CallQueue tasks={[item({ id: "T9" })]} onChanged={onChanged} act={act} />);
    fireEvent.click(screen.getByRole("button", { name: /Complete/ }));
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(act).toHaveBeenCalledWith("A-0001", { action: "COMPLETE", task_id: "T9", snooze_to: undefined });
  });

  it("shows the server's message when a stale action is refused", async () => {
    const act = vi.fn().mockRejectedValue(new CallError("This call task changed since you loaded it. Reload and try again."));
    render(<CallQueue tasks={[item()]} onChanged={vi.fn()} act={act} />);
    fireEvent.click(screen.getByRole("button", { name: /Complete/ }));
    await vi.waitFor(() => expect(screen.getByText(/changed since you loaded it/)).toBeTruthy());
  });
});
