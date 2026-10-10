import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Lead, Snapshot } from "../types";
import { Leads } from "./Leads";

afterEach(cleanup);

function lead(over: Partial<Lead> = {}): Lead {
  const id = over.id ?? "A-0001";
  return {
    id,
    company: `Company ${id}`,
    contact: "",
    email: "sam@example.test",
    phone: "",
    status: "NEW",
    status_label: "New",
    channel: "EMAIL",
    email_check: "OK",
    fit: "QUALIFIED",
    ready: false,
    variant: "",
    tier: "A",
    cells: {},
    action: "",
    blockers: [],
    columns: [],
    events: [],
    gmail_drafts: [],
    ...over,
  } as Lead;
}

function snapshot(over: Partial<Snapshot> & { leads: Lead[] }): Snapshot {
  return {
    version: 1,
    read_at: "",
    today: "",
    today_text: "",
    warnings: [],
    needs_you: [],
    coming_up: [],
    coming_up_days: 0,
    tiers: [{ prefix: "A", label: "A", count: over.leads.length }],
    notes: [],
    drafts: [],
    drafts_summary: { ready: 0, waiting: 0, held: 0, waiting_for_offer: 0 },
    gmail_drafts: [],
    ready: null,
    approvals: null,
    sync: null,
    tracking_run: null,
    event_count: 0,
    suppression_count: null,
    links: { sheet: "", handbook: "", gmail_account: "" },
    signed_in_as: "",
    ...over,
  } as Snapshot;
}

function query(params: Record<string, string> = {}): URLSearchParams {
  return new URLSearchParams(params);
}

describe("leads list — pagination", () => {
  it("shows at most 20 rows per page, with a pager when there are more", () => {
    const leads = Array.from({ length: 25 }, (_, i) => lead({ id: `A-${String(i + 1).padStart(4, "0")}` }));
    render(<Leads data={snapshot({ leads })} query={query()} />);
    expect(screen.getAllByRole("row").length - 1).toBe(20); // minus the header row
    expect(screen.getByText("Page 1 of 2")).toBeTruthy();
  });

  it("no pager at all when everything fits on one page", () => {
    const leads = [lead()];
    render(<Leads data={snapshot({ leads })} query={query()} />);
    expect(screen.queryByText(/Page 1 of/)).toBeNull();
  });

  it("Next moves to the second page's rows", () => {
    const leads = Array.from({ length: 25 }, (_, i) => lead({ id: `A-${String(i + 1).padStart(4, "0")}` }));
    render(<Leads data={snapshot({ leads })} query={query()} />);
    fireEvent.click(screen.getByRole("button", { name: /Next/ }));
    expect(window.location.hash).toContain("page=2");
  });
});

describe("leads list — batch approve", () => {
  const sent = { lead_id: "", sent: true, message_id: "m1", thread_id: "t1", recorded: true, sent_by: "me@x" };

  function readyLead(id: string) {
    return lead({ id, gmail_drafts: [{ kind: "First email", status: "CREATED", at: "", tracked: false }] });
  }

  it("shows no checkboxes when sending is disabled", () => {
    render(<Leads data={snapshot({ leads: [readyLead("A-0001")], send_enabled: false })} query={query()} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("only offers a checkbox for a lead with a created, unsent draft", () => {
    render(
      <Leads
        data={snapshot({
          leads: [readyLead("A-0001"), lead({ id: "A-0002" }), lead({ id: "A-0003", cells: { "Sent at": "x" }, gmail_drafts: [{ kind: "First email", status: "CREATED", at: "", tracked: false }] })],
          send_enabled: true,
        })}
        query={query()}
      />,
    );
    // header checkbox + exactly one row checkbox (A-0001; A-0002 has no draft, A-0003 already sent)
    expect(screen.getAllByRole("checkbox").length).toBe(2);
  });

  it("selecting rows and approving sends each one and reports the outcome", async () => {
    const send = vi.fn(async (id: string) => ({ ...sent, lead_id: id }));
    render(
      <Leads
        data={snapshot({ leads: [readyLead("A-0001"), readyLead("A-0002")], send_enabled: true })}
        query={query()}
        sendDraft={send}
      />,
    );
    const [, firstRow, secondRow] = screen.getAllByRole("checkbox"); // [0] is "select all"
    fireEvent.click(firstRow!);
    fireEvent.click(secondRow!);
    fireEvent.click(screen.getByRole("button", { name: /Approve & send 2/ }));
    fireEvent.click(screen.getByRole("button", { name: /Yes, send 2/ }));
    await waitFor(() => expect(send).toHaveBeenCalledTimes(2));
    expect(send).toHaveBeenCalledWith("A-0001");
    expect(send).toHaveBeenCalledWith("A-0002");
    await waitFor(() => expect(screen.getByText(/Sent 2 of 2/)).toBeTruthy());
  });

  it("reports a partial failure rather than hiding it", async () => {
    const send = vi.fn(async (id: string) => {
      if (id === "A-0002") throw new (await import("../api")).CallError("refused");
      return { ...sent, lead_id: id };
    });
    render(
      <Leads
        data={snapshot({ leads: [readyLead("A-0001"), readyLead("A-0002")], send_enabled: true })}
        query={query()}
        sendDraft={send}
      />,
    );
    fireEvent.click(screen.getByLabelText("Select all ready to send on this page"));
    fireEvent.click(screen.getByRole("button", { name: /Approve & send 2/ }));
    fireEvent.click(screen.getByRole("button", { name: /Yes, send 2/ }));
    await waitFor(() => expect(screen.getByText(/Sent 1 of 2/)).toBeTruthy());
    expect(screen.getByText(/1 failed/)).toBeTruthy();
  });
});
