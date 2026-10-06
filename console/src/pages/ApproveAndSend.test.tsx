import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Lead } from "../types";
import { ApproveAndSend } from "./LeadPage";

const sendDraft = vi.fn();
vi.mock("../api", () => ({ sendDraft: (id: string) => sendDraft(id) }));

afterEach(() => {
  cleanup();
  sendDraft.mockReset();
});

function lead(over: Partial<Lead> = {}): Lead {
  // Only the fields ApproveAndSend reads matter; cast loosely to satisfy the full Lead type.
  const base = {
    id: "A-0001",
    company: "Example Electric",
    contact: "Sam",
    email: "sam@example.test",
    gmail_drafts: [{ kind: "First email", status: "CREATED", at: "2026-10-06", tracked: false }],
    cells: {},
  };
  return { ...base, ...over } as Lead;
}

describe("Approve and send", () => {
  it("sends one email only after a confirm, and reports it sent", async () => {
    sendDraft.mockResolvedValue({
      lead_id: "A-0001", sent: true, message_id: "m-1", thread_id: "t-1", recorded: true, sent_by: "admin@lakshyaa.ai",
    });
    render(<ApproveAndSend lead={lead()} />);
    // the first button does not send; it asks to confirm
    fireEvent.click(screen.getByRole("button", { name: /Approve and send/ }));
    expect(sendDraft).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Yes, send to sam@example.test/ }));
    await waitFor(() => expect(sendDraft).toHaveBeenCalledWith("A-0001"));
    await waitFor(() => expect(screen.getByText(/Sent to sam@example.test/)).toBeTruthy());
  });

  it("offers nothing to send until a draft is created in Gmail", () => {
    render(<ApproveAndSend lead={lead({ gmail_drafts: [{ kind: "First email", status: "RESERVED", at: "", tracked: false }] })} />);
    expect(screen.getByText(/No draft is ready in Gmail yet/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Approve and send/ })).toBeNull();
  });

  it("reports an already-sent lead instead of offering to send again", () => {
    render(<ApproveAndSend lead={lead({ cells: { "Sent at": "2026-10-06T12:00:00+00:00" } })} />);
    expect(screen.getByText(/Sent to sam@example.test/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Approve and send/ })).toBeNull();
  });

  it("surfaces a refusal and does not claim it was sent", async () => {
    sendDraft.mockRejectedValue(new Error("Nothing was sent (this lead has already been sent)."));
    render(<ApproveAndSend lead={lead()} />);
    fireEvent.click(screen.getByRole("button", { name: /Approve and send/ }));
    fireEvent.click(screen.getByRole("button", { name: /Yes, send/ }));
    await waitFor(() => expect(screen.getByText(/already been sent/)).toBeTruthy());
    expect(screen.queryByText(/Sent to sam@example.test\./)).toBeNull();
  });
});
