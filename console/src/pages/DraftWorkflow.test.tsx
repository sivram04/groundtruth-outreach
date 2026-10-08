import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { DraftStepResult } from "../api";
import type { Lead } from "../types";
import { DraftWorkflow } from "./LeadPage";

afterEach(cleanup);

function lead(over: Partial<Lead> = {}): Lead {
  const base = { id: "A-0001", company: "Example Electric", email: "sam@example.test",
                 gmail_drafts: [] as Lead["gmail_drafts"], cells: {} };
  return { ...base, ...over } as Lead;
}

const ok = (over: Partial<DraftStepResult> = {}): DraftStepResult => ({ ok: true, lead_id: "A-0001", ...over });

describe("the draft workflow", () => {
  it("prepares the candidate and shows its status", async () => {
    const prepare = vi.fn(async () => ok({ status: "WAITING", why: "awaiting review" }));
    render(<DraftWorkflow lead={lead()} prepare={prepare} create={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: /Prepare draft for review/ }));
    await waitFor(() => expect(prepare).toHaveBeenCalledWith("A-0001"));
    await waitFor(() => expect(screen.getByText(/WAITING/)).toBeTruthy());
    expect(screen.getByText(/awaiting review/)).toBeTruthy();
  });

  it("creates the Gmail draft and refreshes", async () => {
    const create = vi.fn(async () => ok({ draft_id: "d1", status: "CREATED" }));
    const onChanged = vi.fn();
    render(<DraftWorkflow lead={lead()} prepare={vi.fn()} create={create} onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: /Create Gmail draft/ }));
    await waitFor(() => expect(create).toHaveBeenCalledWith("A-0001"));
    await waitFor(() => expect(screen.getByText(/Gmail draft created/)).toBeTruthy());
    expect(onChanged).toHaveBeenCalled();
  });

  it("links to the lead's review page", () => {
    render(<DraftWorkflow lead={lead()} prepare={vi.fn()} create={vi.fn()} />);
    expect(screen.getByRole("link", { name: /Open review/ }).getAttribute("href")).toBe("#/review/A-0001");
  });

  it("hides itself once a Gmail draft already exists", () => {
    const withDraft = lead({ gmail_drafts: [{ kind: "First email", status: "CREATED", at: "", tracked: false }] });
    const { container } = render(<DraftWorkflow lead={withDraft} prepare={vi.fn()} create={vi.fn()} />);
    expect(container.textContent).toBe("");
  });
});
