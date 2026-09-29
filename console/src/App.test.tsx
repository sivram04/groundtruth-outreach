import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
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

function card(title: string) {
  return screen.getByRole("heading", { name: title }).closest("section")!;
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
    const items = within(card("Needs you")).getAllByRole("listitem");
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

  it("says how many drafts wait for the offer approval, and links to them", async () => {
    await open("#/");
    const note = screen.getByText(/2 drafts are written and waiting for your approval of the offer wording/);
    expect(note.closest(".callout")!.querySelector("a")!.getAttribute("href")).toBe("#/drafts");
    const nav = screen.getByRole("navigation", { name: "Pages" });
    expect(within(nav).getByLabelText("3 drafts").textContent).toBe("3");
  });

  it("shows the pipeline and the numbers per tier as the server worked them out", async () => {
    await open("#/");
    const pipeline = within(card("Pipeline")).getAllByRole("listitem");
    expect(pipeline.map((step) => step.textContent)).toEqual([
      "Leads17",
      "Email checked OK15",
      "Company qualified15",
      "Profiled15",
      "Draft written3",
      "Emailed7",
      "Replied2",
    ]);
    const row = screen.getByRole("cell", { name: "Reply rate" }).parentElement!;
    expect(within(row).getAllByRole("cell").map((cell) => cell.textContent)).toEqual(["Reply rate", "33%", "0%", "29%"]);
    const openRate = screen.getByRole("cell", { name: "Open rate (est.)" }).parentElement!;
    expect(within(openRate).getAllByRole("cell")[1]!.textContent).toBe("-"); // nothing tracked: no rate
    expect(screen.getByText("Tue 2026-09-29")).toBeTruthy(); // coming up
  });
});

describe("the drafts", () => {
  it("shows the draft pointed at, and a different one when another is pointed at", async () => {
    await open("#/drafts");
    const pane = screen.getByRole("complementary", { name: "The draft you are pointing at" });
    expect(within(pane).getByText(/Hi Jo,/)).toBeTruthy();
    const rows = within(screen.getByRole("list", { name: "Drafts" })).getAllByRole("button");
    expect(rows.map((row) => row.querySelector(".draft-company")!.textContent)).toEqual([
      "Lakeside Concrete",
      "Pioneer Paving",
      "Granite Works",
    ]);
    fireEvent.mouseEnter(rows[1]!);
    expect(within(pane).getByText(/Hi Ali,/)).toBeTruthy();
    fireEvent.focus(rows[2]!);
    expect(within(pane).getByText("No words to show: this draft is held.")).toBeTruthy();
    expect(within(pane).getByText("Why it is held")).toBeTruthy();
  });

  it("opens a draft over the page and closes it with Escape", async () => {
    await open("#/drafts");
    const rows = within(screen.getByRole("list", { name: "Drafts" })).getAllByRole("button");
    await act(async () => rows[0]!.click());
    const dialog = screen.getByRole("dialog", { name: "Draft to Lakeside Concrete" });
    expect(within(dialog).getByText("jo@lakeside-concrete.test", { exact: false })).toBeTruthy();
    expect(within(dialog).getByText("You have not approved the offer wording yet")).toBeTruthy();
    expect(within(dialog).getByRole("button", { name: /Approve and send/ }).hasAttribute("disabled")).toBe(true);
    expect(within(dialog).getByRole("button", { name: /Edit/ }).hasAttribute("disabled")).toBe(true);
    expect(document.activeElement?.getAttribute("aria-label")).toBe("Close");
    await act(async () => fireEvent.keyDown(window, { key: "Escape" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("links the page a quote came from only when it is a web address", async () => {
    await open("#/drafts");
    const pane = screen.getByRole("complementary", { name: "The draft you are pointing at" });
    expect(within(pane).getByRole("link", { name: /See the page/ }).getAttribute("href")).toBe(
      "https://lakeside-concrete.test/services",
    );
    const rows = within(screen.getByRole("list", { name: "Drafts" })).getAllByRole("button");
    fireEvent.mouseEnter(rows[1]!);
    expect(within(pane).queryByRole("link", { name: /See the page/ })).toBeNull();
    expect(within(pane).getByText(/javascript:alert\(2\)/).closest("a")).toBeNull();
  });

  it("lists who is ready and not written yet, and what drafting waits for", async () => {
    await open("#/drafts");
    const notYet = card("Ready, not written yet: 1");
    expect(within(notYet).getAllByRole("link").map((link) => link.textContent)).toEqual(["Cobalt Glass"]);
    expect(within(card("What drafting waits for")).getAllByText("Not approved")).toHaveLength(2);
  });

  it("counts in its notice only the drafts waiting for the offer approval", async () => {
    await open("#/drafts", () =>
      Promise.resolve({
        ...structuredClone(data),
        drafts_summary: { ready: 0, waiting: 3, held: 0, waiting_for_offer: 1 },
      }),
    );
    expect(screen.getByText(/1 draft is written and waiting for your approval of the offer wording/)).toBeTruthy();
    expect(screen.getByText("3 waiting for you")).toBeTruthy();
  });

  it("shows no approval notice when nothing waits for the offer approval", async () => {
    await open("#/drafts", () =>
      Promise.resolve({
        ...structuredClone(data),
        drafts_summary: { ready: 0, waiting: 2, held: 1, waiting_for_offer: 0 },
      }),
    );
    expect(screen.queryByText(/waiting for your approval of the offer wording/)).toBeNull();
  });

  it("says so when there are no drafts", async () => {
    await open("#/drafts", () =>
      Promise.resolve({
        ...structuredClone(data),
        drafts: [],
        drafts_summary: { ready: 0, waiting: 0, held: 0, waiting_for_offer: 0 },
      }),
    );
    expect(screen.getByText("No drafts yet")).toBeTruthy();
    expect(screen.queryByRole("complementary", { name: "The draft you are pointing at" })).toBeNull();
  });

  it("says who is ready cannot be told when the Suppression tab cannot be read", async () => {
    await open("#/drafts", () => Promise.resolve({ ...structuredClone(data), ready: null }));
    expect(screen.getByText("This cannot be told: the Suppression tab cannot be read.")).toBeTruthy();
    await go("#/");
    const row = screen.getByRole("cell", { name: "Ready for a first draft" }).parentElement!;
    expect(within(row).getAllByRole("cell")[1]!.textContent).toBe("?");
  });
});

describe("the other pages", () => {
  it("filters the leads from the address, and marks a lead's draft", async () => {
    await open("#/leads?show=ready");
    expect(screen.getByText("4 of 17 leads", { selector: "p" })).toBeTruthy();
    expect(screen.getAllByText("Draft: waiting for you").length).toBe(2);
    await go("#/leads?tier=B");
    expect(screen.getByText("3 of 17 leads", { selector: "p" })).toBeTruthy();
    const tab = screen.getByRole("link", { name: "Replied" });
    expect(tab.getAttribute("href")).toBe("#/leads?tier=B&show=replied");
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

  it("gives a lead's draft, history and every column of its row", async () => {
    await open("#/leads/A-0007");
    expect(within(card("The draft")).getByText(/Hi Jo,/)).toBeTruthy();
    await go("#/leads/A-0005");
    expect(screen.getByText("5.1.1 address not found")).toBeTruthy();
    expect(screen.getByText("Every column of this lead in the Sheet")).toBeTruthy();
    expect(screen.getByText("Sent by hand")).toBeTruthy();
  });

  it("says where the data comes from without the founder's address or phone", async () => {
    await open("#/sources");
    expect(screen.getByRole("link", { name: /Open the leads Sheet/ }).getAttribute("href")).toBe(data.links.sheet);
    expect(screen.getByText("admin@lakshyaa.ai", { selector: "dd" })).toBeTruthy();
    expect(document.body.textContent).not.toContain("+1 555 010 0000");
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

describe("the dashboard's leads table", () => {
  it("counts each tab and narrows the table when one is chosen", async () => {
    await open("#/");
    const tabs = screen.getByRole("tablist", { name: "Which leads" });
    const named = (name: string) => within(tabs).getByRole("tab", { name: new RegExp(`^${name}`) });
    expect(named("All leads").textContent).toBe("All leads17");
    expect(named("Replied").textContent).toBe("Replied1");
    expect(named("Ready for a first draft").textContent).toBe("Ready for a first draft4");
    expect(within(screen.getAllByRole("table")[0]!).getAllByRole("row").length - 1).toBe(17);
    await act(async () => named("Replied").click());
    const rows = within(screen.getAllByRole("table")[0]!).getAllByRole("row");
    expect(rows.length - 1).toBe(1);
    expect(within(rows[1]!).getByRole("link", { name: "Acme Plumbing" })).toBeTruthy();
  });

  it("searches within the tab that is open", async () => {
    await open("#/");
    const box = screen.getByLabelText("Search leads");
    fireEvent.change(box, { target: { value: "acme" } });
    const rows = within(screen.getAllByRole("table")[0]!).getAllByRole("row");
    expect(rows.length - 1).toBe(1);
    expect(within(rows[1]!).getByRole("link", { name: "Acme Plumbing" })).toBeTruthy();
  });
});
