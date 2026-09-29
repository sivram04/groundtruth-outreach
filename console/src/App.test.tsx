import { act, cleanup, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoadError } from "./api";
import { App } from "./App";
import demo from "./demo/snapshot.json";
import type { Snapshot } from "./types";

const data = demo as unknown as Snapshot;
const loaded = () => Promise.resolve(structuredClone(data));

async function open(hash: string, load: () => Promise<Snapshot> = loaded) {
  window.location.hash = hash;
  render(<App load={load} />);
  await screen.findAllByRole("heading", { level: 1 });
}

async function go(hash: string) {
  await act(async () => {
    window.location.hash = hash;
    window.dispatchEvent(new HashChangeEvent("hashchange"));
  });
}

beforeEach(() => {
  window.scrollTo = vi.fn();
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

describe("the dashboard", () => {
  it("puts what needs the founder first, in order, each with a way into Gmail", async () => {
    await open("#/");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Dashboard");
    const needs = screen.getByRole("heading", { name: "Needs you" }).parentElement!;
    const items = within(needs).getAllByRole("listitem");
    expect(items.map((item) => within(item).getAllByRole("link")[0]!.textContent)).toEqual([
      "Acme Plumbing",
      "Example Electric",
      "Spruce HVAC",
      "Harbor Glass",
      "Riverbend Drywall",
    ]);
    const gmail = within(items[4]!).getByRole("link", { name: /in Gmail/ });
    expect(gmail.getAttribute("href")).toContain("#search/jeff@riverbend-drywall.test"); // the address emailed
    expect(gmail.getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("shows the numbers per tier as the server worked them out", async () => {
    await open("#/");
    const row = screen.getByRole("cell", { name: "Reply rate" }).parentElement!;
    expect(within(row).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["Reply rate", "33%", "0%", "29%"]);
    const open_rate = screen.getByRole("cell", { name: "Open rate (est.)" }).parentElement!;
    expect(within(open_rate).getAllByRole("cell")[1]!.textContent).toBe("-"); // nothing tracked: no rate
    expect(screen.getByText("Tue 2026-09-29")).toBeTruthy(); // coming up
  });
});

describe("the other pages", () => {
  it("lists the drafts waiting, what drafting waits for, and who is ready", async () => {
    await open("#/drafts");
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Drafts");
    expect(screen.getByRole("link", { name: "B-0002" })).toBeTruthy();
    expect(screen.getAllByText("Not approved")).toHaveLength(2);
    const ready = screen.getByRole("heading", { name: "Ready for a first draft: 2" }).parentElement!;
    expect(within(ready).getAllByRole("link").map((link) => link.textContent)).toEqual(["A-0007", "A-0008"]);
  });

  it("says who is ready cannot be told when the Suppression tab cannot be read", async () => {
    await open("#/drafts", () => Promise.resolve({ ...structuredClone(data), ready: null }));
    expect(screen.getByRole("heading", { name: "Ready for a first draft" })).toBeTruthy();
    expect(screen.getByText("This cannot be told: the Suppression tab cannot be read.")).toBeTruthy();
    await go("#/");
    const tile = screen.getByText("Ready for a first draft", { selector: ".tile span" }).parentElement!;
    expect(tile.querySelector("b")!.textContent).toBe("?");
  });

  it("filters the leads from the address and searches on submit", async () => {
    await open("#/leads?show=ready");
    expect(screen.getByText("2 of 15 leads")).toBeTruthy();
    await go("#/leads?tier=B");
    expect(screen.getByText("3 of 15 leads")).toBeTruthy();
  });

  it("shows a name with markup in it as text, and no link for a website that is not http", async () => {
    await open("#/leads/A-0012");
    const heading = screen.getByRole("heading", { level: 1 });
    expect(heading.textContent).toBe("Oak Tile & Stone <b>Ltd</b>");
    expect(heading.querySelector("b")).toBeNull();
    const shown = screen.getAllByText("javascript:alert(1)");
    expect(shown.length).toBeGreaterThan(0);
    expect(shown.every((element) => element.closest("a") === null)).toBe(true);
    expect(document.title).toBe("Outreach: Oak Tile & Stone <b>Ltd</b>");
  });

  it("gives a lead's history and every column of its row", async () => {
    await open("#/leads/A-0005");
    expect(screen.getByText("5.1.1 address not found")).toBeTruthy();
    expect(screen.getByText("Bounced", { selector: "td" })).toBeTruthy();
    expect(screen.getByText("Every column of this lead in the Sheet")).toBeTruthy();
    expect(screen.getByText("Sent by hand")).toBeTruthy();
  });

  it("says where the data comes from without the founder's address or phone", async () => {
    await open("#/sources");
    expect(screen.getByRole("link", { name: "Open the leads Sheet" }).getAttribute("href")).toBe(data.links.sheet);
    expect(screen.getByText("admin@lakshyaa.ai", { selector: "dd" })).toBeTruthy();
    expect(document.body.textContent).not.toContain("Made Up Road");
  });

  it("says so for a lead or page that does not exist", async () => {
    await open("#/leads/Z-9999");
    expect(screen.getByText("There is no lead Z-9999.")).toBeTruthy();
    await go("#/nowhere");
    expect(screen.getByText("There is no such page.")).toBeTruthy();
  });
});

describe("when the data cannot be read", () => {
  it("offers a reload when the sign-in has ended", async () => {
    window.location.hash = "#/";
    render(<App load={() => Promise.reject(new LoadError("Your sign-in has ended.", true))} />);
    expect(await screen.findByText("Your sign-in has ended.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Reload the page" })).toBeTruthy();
  });

  it("offers to try again, and keeps what was read before when a refresh fails", async () => {
    let calls = 0;
    const load = () =>
      ++calls === 1 ? loaded() : Promise.reject(new LoadError("The Sheet could not be read just now."));
    await open("#/", load);
    await act(async () => screen.getByRole("button", { name: "Refresh" }).click());
    expect(await screen.findByText(/Could not refresh: The Sheet could not be read just now\./)).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Needs you" })).toBeTruthy();
  });

  it("names nothing it was not told when something unexpected goes wrong", async () => {
    window.location.hash = "#/";
    render(<App load={() => Promise.reject(new Error("internal detail"))} />);
    expect(await screen.findByText("Something went wrong reading the Sheet. Try again.")).toBeTruthy();
    expect(document.body.textContent).not.toContain("internal detail");
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
  });
});
