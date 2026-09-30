import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportError } from "../api";
import type { ImportPreview } from "../types";
import { Import } from "./Import";

const PREVIEW: ImportPreview = {
  prefix: "A",
  destination_columns: ["Lead ID", "Company", "BEST EMAIL", "Phone"],
  accepted: [
    { lead_id: "A-0002", channel: "EMAIL", row: { Company: "Bluebird Electric", "BEST EMAIL": "dana@bluebird-electric.test" }, unstorable: [] },
    { lead_id: "A-0003", channel: "CALL", row: { Company: "Redwood Plumbing", Phone: "(614) 555-0142" }, unstorable: [{ field: "Location", value: "Dublin OH" }] },
    { lead_id: "A-0004", channel: "COMPANY_ONLY", row: { Company: "Cedar Roofing" }, unstorable: [] },
  ],
  duplicates: [{ record: { Company: "Example Electric" }, matched: "A-0001", reason: "already present as A-0001" }],
  skipped: [{ record: {}, reason: "no company, email or phone to import" }],
  unstorable_fields: ["Location"],
  summary: { accepted: 3, duplicates: 1, skipped: 1, unstorable: 1, by_channel: { EMAIL: 1, CALL: 1, COMPANY_ONLY: 1 } },
  fingerprint: "fp123",
};

afterEach(cleanup);

async function previewed(commit = vi.fn()) {
  const preview = vi.fn().mockResolvedValue(PREVIEW);
  const onImported = vi.fn();
  render(<Import onImported={onImported} preview={preview} commit={commit} />);
  fireEvent.change(screen.getByLabelText(/Paste rows/), { target: { value: "Company\nAcme" } });
  fireEvent.click(screen.getByRole("button", { name: /Preview/ }));
  await screen.findByText("A-0003");
  return { preview, commit, onImported };
}

describe("the import page", () => {
  it("previews what would be stored, keeping email, call and company-only, and flagging unstorable fields", async () => {
    const { preview } = await previewed();
    expect(preview).toHaveBeenCalledWith({ text: "Company\nAcme", prefix: "A" });
    // every kind is shown
    expect(screen.getByText("A-0002")).toBeTruthy();
    expect(screen.getByText("A-0004")).toBeTruthy();
    expect(screen.getAllByText("Call").length).toBeGreaterThan(0);
    expect(screen.getByText("No contact")).toBeTruthy();
    // a field with no column is shown, not hidden
    expect(screen.getByText(/not stored: Location/)).toBeTruthy();
    expect(screen.getByText(/have no column in tab A/)).toBeTruthy();
    // duplicates and skipped are visible
    expect(screen.getByText("A-0001")).toBeTruthy();
    expect(screen.getByText(/no company, email or phone/)).toBeTruthy();
    expect(screen.getByText(/3 to add · 1 already present · 1 skipped/)).toBeTruthy();
  });

  it("confirms once, sends the fingerprint, and shows what was imported", async () => {
    const commit = vi.fn().mockResolvedValue({ written: 3, already_present: 0, lead_ids: ["A-0002", "A-0003", "A-0004"] });
    const { onImported } = await previewed(commit);
    fireEvent.click(screen.getByRole("button", { name: /Import 3 leads/ }));
    await screen.findByText(/Imported 3 leads \(A-0002, A-0003, A-0004\)/);
    expect(commit).toHaveBeenCalledWith("A", PREVIEW.accepted.map((a) => a.row), "fp123");
    expect(onImported).toHaveBeenCalledTimes(1);
    // the confirm control is gone: it cannot be pressed twice
    expect(screen.queryByRole("button", { name: /Import 3 leads/ })).toBeNull();
    expect(screen.getByRole("link", { name: /View the leads/ }).getAttribute("href")).toBe("#/leads");
  });

  it("a stale preview is refused and must be redone before anything is written", async () => {
    const commit = vi.fn().mockRejectedValue(new ImportError("The preview is out of date. Preview again.", { stale: true }));
    await previewed(commit);
    fireEvent.click(screen.getByRole("button", { name: /Import 3 leads/ }));
    await screen.findByText(/out of date/);
    // the preview is cleared, so nothing can be committed from it
    expect(screen.queryByText("A-0003")).toBeNull();
    expect(screen.queryByRole("button", { name: /Import 3 leads/ })).toBeNull();
  });

  it("an uncertain commit is reported without claiming nothing was written", async () => {
    const commit = vi.fn().mockRejectedValue(new ImportError("The outcome is uncertain. Reload the leads to check.", { uncertain: true }));
    await previewed(commit);
    fireEvent.click(screen.getByRole("button", { name: /Import 3 leads/ }));
    await screen.findByText(/uncertain/);
    // the preview stays so the founder can reload and see, not a false success
    expect(screen.getByText("A-0003")).toBeTruthy();
  });
});
