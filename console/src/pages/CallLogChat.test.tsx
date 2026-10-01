import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CallError } from "../api";
import type { CallProposal } from "../types";
import { CallLogChat } from "./CallLogChat";

afterEach(cleanup);

const READY: CallProposal = {
  status: "ready",
  lead: { lead_id: "A-0002", company: "Bluebird Electric", contact: "Dana Ray", email: "dana@bluebird.test", phone: "614-555-0100" },
  outcome: "NO_ANSWER", note: "no answer", due_text: "Thu 2026-10-01", effect: "CONTINUE",
  do_not_contact: false, submission_id: "chat-abc",
};

function type(value: string) {
  fireEvent.change(screen.getByPlaceholderText(/Called Dana/), { target: { value } });
}

describe("chat call logging", () => {
  it("reads a note, shows the proposal, and writes only on confirm", async () => {
    const interpret = vi.fn().mockResolvedValue(READY);
    const record = vi.fn().mockResolvedValue({ recorded: true, task: null, history: [], effect: "CONTINUE" });
    const onChanged = vi.fn();
    render(<CallLogChat onChanged={onChanged} interpret={interpret} record={record} />);
    type("Called Bluebird, no answer");
    fireEvent.click(screen.getByRole("button", { name: /Read it/ }));
    await vi.waitFor(() => expect(screen.getByText("Bluebird Electric")).toBeTruthy());
    expect(screen.getByText("Thu 2026-10-01")).toBeTruthy();
    expect(record).not.toHaveBeenCalled(); // nothing written before confirm
    fireEvent.click(screen.getByRole("button", { name: /Confirm and save/ }));
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(record).toHaveBeenCalledWith("A-0002", {
      outcome: "NO_ANSWER", note: "no answer", callback_at: undefined, submission_id: "chat-abc",
    });
  });

  it("asks the founder to choose when several leads match", async () => {
    const proposal: CallProposal = {
      status: "choose_lead", outcome: "NO_ANSWER", note: "called Bluebird, no answer",
      leads: [
        { lead_id: "A-0010", company: "Bluebird Electric", contact: "Dana", email: "d@x.test", phone: "" },
        { lead_id: "A-0011", company: "Bluebird Plumbing", contact: "Alex", email: "a@y.test", phone: "" },
      ],
    };
    const interpret = vi.fn().mockResolvedValueOnce(proposal).mockResolvedValue(READY);
    render(<CallLogChat onChanged={vi.fn()} interpret={interpret} record={vi.fn()} />);
    type("called Bluebird, no answer");
    fireEvent.click(screen.getByRole("button", { name: /Read it/ }));
    await vi.waitFor(() => expect(screen.getByText("Which lead did you mean?")).toBeTruthy());
    fireEvent.click(screen.getAllByRole("button", { name: /Use this one/ })[1]!);
    await vi.waitFor(() => expect(interpret).toHaveBeenCalledTimes(2));
    expect(interpret.mock.calls[1]![1]).toEqual({ lead_id: "A-0011" });
  });

  it("requires an explicit callback time, never guessing from the note", async () => {
    const need: CallProposal = {
      status: "need_time", outcome: "CALLBACK", note: "wants a call back next week",
      lead: { lead_id: "A-0002", company: "Bluebird", contact: "Dana", email: "d@x.test", phone: "" },
    };
    const interpret = vi.fn().mockResolvedValueOnce(need).mockResolvedValue(READY);
    render(<CallLogChat onChanged={vi.fn()} interpret={interpret} record={vi.fn()} />);
    type("Bluebird wants a call back next week");
    fireEvent.click(screen.getByRole("button", { name: /Read it/ }));
    await vi.waitFor(() => expect(screen.getByText(/needs an explicit date and time/)).toBeTruthy());
    fireEvent.change(screen.getByLabelText(/Callback at/), { target: { value: "2026-10-02T14:00" } });
    fireEvent.click(screen.getByRole("button", { name: /Use this time/ }));
    await vi.waitFor(() => expect(interpret).toHaveBeenCalledTimes(2));
    expect(interpret.mock.calls[1]![1].lead_id).toBe("A-0002");
    expect(typeof interpret.mock.calls[1]![1].callback_at).toBe("string");
  });

  it("shows a do-not-contact as a clear sticky stop", async () => {
    const dnc: CallProposal = { ...READY, outcome: "DO_NOT_CONTACT", effect: "STOP", do_not_contact: true };
    const interpret = vi.fn().mockResolvedValue(dnc);
    render(<CallLogChat onChanged={vi.fn()} interpret={interpret} record={vi.fn()} />);
    type("Bluebird, do not contact");
    fireEvent.click(screen.getByRole("button", { name: /Read it/ }));
    await vi.waitFor(() => expect(screen.getByText(/permanent stop on outreach/)).toBeTruthy());
  });

  it("shows a partial-success warning and repairs the suppression write without a second call", async () => {
    // The real partial-success response shape: HTTP 200, recorded true, suppression_written false, warning.
    const interpret = vi.fn().mockResolvedValue({ ...READY, outcome: "DO_NOT_CONTACT", do_not_contact: true });
    const record = vi
      .fn()
      .mockResolvedValueOnce({ recorded: true, task: null, history: [], effect: "STOP",
                               suppression_written: false, warning: "the suppression list could not be written" })
      .mockResolvedValue({ recorded: true, task: null, history: [], effect: "STOP", suppression_written: true });
    const onChanged = vi.fn();
    render(<CallLogChat onChanged={onChanged} interpret={interpret} record={record} />);
    type("Bluebird, do not contact");
    fireEvent.click(screen.getByRole("button", { name: /Read it/ }));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /Confirm and save/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Confirm and save/ }));
    await vi.waitFor(() => expect(screen.getByText(/suppression list could not be written/)).toBeTruthy());
    expect(screen.queryByText(/^Saved for/)).toBeNull(); // not a clean "Saved"
    fireEvent.click(screen.getByRole("button", { name: /Retry the suppression write/ }));
    await vi.waitFor(() => expect(record).toHaveBeenCalledTimes(2));
    expect(record.mock.calls[1]![1].submission_id).toBe("chat-abc"); // same submission, no second call
    await vi.waitFor(() => expect(screen.queryByText(/suppression list could not be written/)).toBeNull());
  });

  it("keeps the proposal and submission id to retry after a failed confirm", async () => {
    const interpret = vi.fn().mockResolvedValue(READY);
    const record = vi
      .fn()
      .mockRejectedValueOnce(new CallError("The call could not be recorded."))
      .mockResolvedValue({ recorded: true, task: null, history: [], effect: "CONTINUE" });
    const onChanged = vi.fn();
    render(<CallLogChat onChanged={onChanged} interpret={interpret} record={record} />);
    type("Called Bluebird, no answer");
    fireEvent.click(screen.getByRole("button", { name: /Read it/ }));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /Confirm and save/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Confirm and save/ }));
    await vi.waitFor(() => expect(screen.getByText("The call could not be recorded.")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Try again/ }));
    await vi.waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(record.mock.calls[0]![1].submission_id).toBe("chat-abc");
    expect(record.mock.calls[1]![1].submission_id).toBe("chat-abc"); // same submission across the retry
  });
});
