import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { LeadChangeResult, LeadChatProposal } from "../types";
import { LeadChat } from "./LeadChat";

afterEach(cleanup);

const propose = (p: LeadChatProposal) => () => Promise.resolve(p);

function setup(proposal: LeadChatProposal, apply = vi.fn(() => Promise.resolve<LeadChangeResult>({ ok: true, op: "add", lead_id: "A-abc123" }))) {
  render(<LeadChat onChanged={() => {}} interpret={propose(proposal)} apply={apply} />);
  return apply;
}

async function readWith(text: string) {
  fireEvent.change(screen.getByPlaceholderText(/add \| Company/), { target: { value: text } });
  fireEvent.click(screen.getByRole("button", { name: /Read it/ }));
}

describe("the lead-management chat", () => {
  it("proposes an add, shows the fields, and writes only on confirm", async () => {
    const apply = setup({
      status: "ready", op: "add",
      fields: { Company: "Acme Electric", "BEST EMAIL": "sam@acme.test" },
      submission_id: "leadchat-1",
    });
    await readWith("add | Company: Acme Electric | email: sam@acme.test");
    await waitFor(() => expect(screen.getByText("Acme Electric")).toBeTruthy());
    expect(apply).not.toHaveBeenCalled(); // nothing written until confirm
    fireEvent.click(screen.getByRole("button", { name: /Confirm and save/ }));
    await waitFor(() => expect(apply).toHaveBeenCalledWith({
      op: "add", lead_id: undefined, fields: { Company: "Acme Electric", "BEST EMAIL": "sam@acme.test" },
    }));
    await waitFor(() => expect(screen.getByText(/Added A-abc123/)).toBeTruthy());
  });

  it("shows a protected-column message and offers no confirm", async () => {
    setup({ status: "protected", lead_id: "A-0001", columns: ["BEST EMAIL"] });
    await readWith("update A-0001 | email: new@x.test");
    await waitFor(() => expect(screen.getByText(/protected/)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Confirm and save/ })).toBeNull();
  });

  it("surfaces a bad email without claiming a change", async () => {
    setup({ status: "bad_email", value: "not-an-email" });
    await readWith("add | Company: X | email: not-an-email");
    await waitFor(() => expect(screen.getByText(/not look valid/)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Confirm and save/ })).toBeNull();
  });

  it("confirms an update with the right payload", async () => {
    const apply = setup(
      { status: "ready", op: "update", lead_id: "A-0001", company: "Existing", fields: { Fit: "QUALIFIED" } },
      vi.fn(() => Promise.resolve<LeadChangeResult>({ ok: true, op: "update", lead_id: "A-0001" })),
    );
    await readWith("update A-0001 | fit: QUALIFIED");
    await waitFor(() => expect(screen.getByText("Fit")).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Confirm and save/ }));
    await waitFor(() => expect(apply).toHaveBeenCalledWith({ op: "update", lead_id: "A-0001", fields: { Fit: "QUALIFIED" } }));
  });
});
