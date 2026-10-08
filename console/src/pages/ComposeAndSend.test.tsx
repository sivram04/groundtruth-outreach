import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Draft, Lead } from "../types";
import { ComposeAndSend } from "./ComposeAndSend";

afterEach(cleanup);

function lead(over: Partial<Lead> = {}): Lead {
  const base = { id: "A-0001", email: "sam@example.test", gmail_drafts: [] as Lead["gmail_drafts"], cells: {} };
  return { ...base, ...over } as Lead;
}

function draft(over: Partial<Draft> = {}): Draft {
  return { lead_id: "A-0001", subject: "A quick question", body: "Hi Sam,\n\nFirst draft.", ...over } as Draft;
}

const sent = { lead_id: "A-0001", sent: true, message_id: "m1", thread_id: "t1", recorded: true, sent_by: "me@x" };

describe("compose and send", () => {
  it("pre-fills from the composed draft and sends exactly the edited words", async () => {
    const sendEdited = vi.fn(async () => sent);
    render(<ComposeAndSend lead={lead()} draft={draft()} compose={vi.fn()} sendEdited={sendEdited} sendCreated={vi.fn()} />);
    const subject = screen.getByDisplayValue("A quick question") as HTMLInputElement;
    const body = screen.getByDisplayValue(/First draft/) as HTMLTextAreaElement;
    fireEvent.change(subject, { target: { value: "My own subject" } });
    fireEvent.change(body, { target: { value: "My own words." } });
    fireEvent.click(screen.getByRole("button", { name: /Approve and send/ }));
    fireEvent.click(screen.getByRole("button", { name: /Yes, send to/ }));
    await waitFor(() => expect(sendEdited).toHaveBeenCalledWith("A-0001", "My own subject", "My own words."));
    await waitFor(() => expect(screen.getByText(/Sent to sam@example.test/)).toBeTruthy());
  });

  it("offers to write a first draft when none exists", async () => {
    const compose = vi.fn(async () => ({ ok: true, lead_id: "A-0001", status: "WAITING" }));
    render(<ComposeAndSend lead={lead()} compose={compose} sendEdited={vi.fn()} sendCreated={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Write a first draft for me/ }));
    await waitFor(() => expect(compose).toHaveBeenCalledWith("A-0001"));
  });

  it("sends an already-created Gmail draft as it is", async () => {
    const sendCreated = vi.fn(async () => sent);
    const withDraft = lead({ gmail_drafts: [{ kind: "First email", status: "CREATED", at: "", tracked: false }] });
    render(<ComposeAndSend lead={withDraft} compose={vi.fn()} sendEdited={vi.fn()} sendCreated={sendCreated} />);
    fireEvent.click(screen.getByRole("button", { name: /Approve and send/ }));
    fireEvent.click(screen.getByRole("button", { name: /Yes, send to/ }));
    await waitFor(() => expect(sendCreated).toHaveBeenCalledWith("A-0001"));
  });

  it("just reports a lead that is already sent", () => {
    render(<ComposeAndSend lead={lead({ cells: { "Sent at": "2026-10-08" } })} compose={vi.fn()} sendEdited={vi.fn()} sendCreated={vi.fn()} />);
    expect(screen.getByText(/Sent to sam@example.test/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Approve and send/ })).toBeNull();
  });

  it("disables send until there is a subject and a body", () => {
    render(<ComposeAndSend lead={lead()} draft={draft({ subject: "", body: "" })} compose={vi.fn()} sendEdited={vi.fn()} sendCreated={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Approve and send/ }).hasAttribute("disabled")).toBe(true);
  });
});
