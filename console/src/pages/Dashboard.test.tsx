import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { App } from "../App";
import demo from "../demo/snapshot.json";
import type { Snapshot } from "../types";

const data = demo as unknown as Snapshot;
const loaded = (over: Partial<Snapshot> = {}) => () => Promise.resolve({ ...structuredClone(data), ...over });

beforeEach(() => {
  window.scrollTo = vi.fn();
  Element.prototype.scrollTo = vi.fn();
  window.location.hash = "#/";
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

async function open(over: Partial<Snapshot> = {}) {
  render(<App load={loaded(over)} ask={vi.fn()} />);
  await screen.findAllByRole("heading", { level: 1 });
}

describe("the dashboard's ready-for-a-first-draft section", () => {
  it("lists a lead that is ready but has no draft yet, with a way straight to it", async () => {
    await open();
    const section = screen.getByRole("heading", { name: "Ready for a first draft" }).closest("section")!;
    // A-0014 is ready and undrafted in the demo fixture; the other three ready leads already
    // have a draft, so they must not appear here.
    expect(within(section).getByRole("heading", { name: /Cobalt Glass/ })).toBeTruthy();
    expect(within(section).getAllByRole("link", { name: /Write & approve/ }).length).toBe(1);
  });

  it("is absent when nothing is ready without a draft", async () => {
    const leads = data.leads.map((lead) => (lead.id === "A-0014" ? { ...lead, ready: false } : lead));
    await open({ leads });
    expect(screen.queryByRole("heading", { name: "Ready for a first draft" })).toBeNull();
  });

  it("links to the Leads page filtered to Ready when there are more than shown", async () => {
    const extra = Array.from({ length: 6 }, (_, i) => ({
      ...data.leads.find((l) => l.id === "A-0014")!, id: `A-900${i}`, company: `Extra ${i}`,
    }));
    await act(async () => {});
    await open({ leads: [...data.leads, ...extra] });
    const section = screen.getByRole("heading", { name: "Ready for a first draft" }).closest("section")!;
    expect(within(section).getByRole("link", { name: /See all 7/ }).getAttribute("href")).toBe("#/leads?show=ready");
    // Capped at 5 cards even though 7 are ready-and-undrafted.
    expect(within(section).getAllByRole("link", { name: /Write & approve/ }).length).toBe(5);
  });
});
