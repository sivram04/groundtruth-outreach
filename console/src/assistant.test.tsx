import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { LoadError, type Answer } from "./api";
import { App } from "./App";
import demo from "./demo/snapshot.json";
import type { Snapshot } from "./types";

const data = demo as unknown as Snapshot;
const loaded = () => Promise.resolve(structuredClone(data));

function answering(answer: Partial<Answer>) {
  const ask = vi.fn(async () => ({ answer: "Nothing needs you.", refused: false, ...answer }) as Answer);
  return ask;
}

async function open(ask: ReturnType<typeof answering>) {
  window.location.hash = "#/";
  render(<App load={loaded} ask={ask} />);
  await screen.findAllByRole("heading", { level: 1 });
  return screen.getByRole("complementary", { name: "Assistant" });
}

function typeAndSend(panel: HTMLElement, question: string) {
  const box = within(panel).getByLabelText("Ask the assistant");
  fireEvent.change(box, { target: { value: question } });
  return act(async () => {
    within(panel).getByRole("button", { name: "Ask" }).click();
  });
}

beforeEach(() => {
  window.scrollTo = vi.fn();
  window.localStorage.clear();
  Element.prototype.scrollTo = vi.fn();
});

afterEach(() => {
  cleanup();
  window.location.hash = "";
});

describe("the assistant", () => {
  it("opens with what it can do, and says it cannot send", async () => {
    const panel = await open(answering({}));
    expect(within(panel).getByRole("heading", { name: "How can I help?" })).toBeTruthy();
    expect(within(panel).getByText(/I cannot send or change anything/)).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "What needs me today?" })).toBeTruthy();
  });

  it("asks what the founder typed and shows the answer with its leads and link", async () => {
    const ask = answering({
      answer: "Acme Plumbing replied. Answer it by hand.",
      lead_ids: ["A-0002"],
      link: { page: "lead", lead_id: "A-0002", show: "", label: "Open Acme Plumbing" },
    });
    const panel = await open(ask);
    await typeAndSend(panel, "who replied?");
    expect(ask).toHaveBeenCalledWith("who replied?");
    await waitFor(() => expect(within(panel).getByText("Acme Plumbing replied. Answer it by hand.")).toBeTruthy());
    expect(within(panel).getByText("who replied?")).toBeTruthy();
    // The lead is named by its company, and both it and the link go to pages this app has.
    expect(within(panel).getByRole("link", { name: "Acme Plumbing" }).getAttribute("href")).toBe("#/leads/A-0002");
    expect(within(panel).getByRole("link", { name: "Open Acme Plumbing" }).getAttribute("href")).toBe("#/leads/A-0002");
  });

  it("asks a suggested question with one click", async () => {
    const ask = answering({});
    const panel = await open(ask);
    await act(async () => within(panel).getByRole("button", { name: "Has anyone replied?" }).click());
    expect(ask).toHaveBeenCalledWith("Has anyone replied?");
  });

  it("marks a refused answer and shows nothing else", async () => {
    const panel = await open(
      answering({ answer: "I could not answer that from your Sheet.", refused: true, lead_ids: [] }),
    );
    await typeAndSend(panel, "how much will they pay me?");
    const said = await within(panel).findByText("I could not answer that from your Sheet.");
    expect(said.closest(".bubble")!.className).toContain("refused");
  });

  it("says so when the assistant cannot be reached, and never blanks the page", async () => {
    const ask = vi.fn(() => Promise.reject(new LoadError("The console could not be reached.")));
    const panel = await open(ask as unknown as ReturnType<typeof answering>);
    await typeAndSend(panel, "anything");
    expect(await within(panel).findByText("The console could not be reached.")).toBeTruthy();
    expect(screen.getByRole("heading", { level: 1 }).textContent).toBe("Dashboard");
  });

  it("sends on Enter, keeps Shift+Enter for a new line, and asks nothing for empty words", async () => {
    const ask = answering({});
    const panel = await open(ask);
    const box = within(panel).getByLabelText("Ask the assistant");
    fireEvent.change(box, { target: { value: "   " } });
    await act(async () => fireEvent.keyDown(box, { key: "Enter" }));
    expect(ask).not.toHaveBeenCalled();
    fireEvent.change(box, { target: { value: "what needs me?" } });
    await act(async () => fireEvent.keyDown(box, { key: "Enter", shiftKey: true }));
    expect(ask).not.toHaveBeenCalled();
    await act(async () => fireEvent.keyDown(box, { key: "Enter" }));
    expect(ask).toHaveBeenCalledWith("what needs me?");
  });

  it("can be hidden and brought back, and is remembered in this browser", async () => {
    const panel = await open(answering({}));
    await act(async () => within(panel).getByRole("button", { name: "Hide the assistant" }).click());
    expect(screen.queryByRole("complementary", { name: "Assistant" })).toBeNull();
    expect(window.localStorage.getItem("outreach.assistant")).toBe("off");
    await act(async () => screen.getByRole("button", { name: "Ask" }).click());
    expect(screen.getByRole("complementary", { name: "Assistant" })).toBeTruthy();
    expect(window.localStorage.getItem("outreach.assistant")).toBe("on");
  });
});

describe("on a phone", () => {
  it("stays closed until it is asked for, and then covers the page", async () => {
    window.matchMedia = ((query: string) => ({
      matches: false,
      media: query,
      addEventListener() {},
      removeEventListener() {},
    })) as unknown as typeof window.matchMedia;
    window.location.hash = "#/";
    render(<App load={loaded} ask={answering({})} />);
    await screen.findAllByRole("heading", { level: 1 });
    expect(screen.queryByRole("complementary", { name: "Assistant" })).toBeNull();
    await act(async () => screen.getByRole("button", { name: "Ask" }).click());
    expect(screen.getByRole("complementary", { name: "Assistant" })).toBeTruthy();
  });
});
