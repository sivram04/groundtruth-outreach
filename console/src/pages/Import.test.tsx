import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ImportError } from "../api";
import type { ImportPreview } from "../types";
import { Import } from "./Import";

const PREVIEW: ImportPreview = {
  prefix: "A",
  destination_columns: ["Lead ID", "Company", "BEST EMAIL", "Phone"],
  accepted: [
    { lead_id: "A-0002", channel: "EMAIL", row: { Company: "Bluebird Electric", "BEST EMAIL": "dana@bluebird-electric.test" }, unstorable: [], invalid: [{ field: "phone", value: "12", reason: "not enough digits for a phone number" }] },
    { lead_id: "A-0003", channel: "CALL", row: { Company: "Redwood Plumbing", Phone: "(614) 555-0142" }, unstorable: [{ field: "Location", value: "Dublin OH" }], invalid: [] },
    { lead_id: "A-0004", channel: "COMPANY_ONLY", row: { Company: "Cedar Roofing" }, unstorable: [], invalid: [] },
  ],
  duplicates: [{ record: { Company: "Example Electric" }, matched: "A-0001", reason: "already present as A-0001" }],
  skipped: [{ record: {}, reason: "no company, email or phone to import" }],
  unstorable_fields: ["Location"],
  summary: { accepted: 3, duplicates: 1, skipped: 1, unstorable: 1, invalid: 1, by_channel: { EMAIL: 1, CALL: 1, COMPANY_ONLY: 1 } },
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
    // an invalid contact value is shown with why, never silently discarded
    expect(screen.getByText(/cannot use: phone "12" — not enough digits/)).toBeTruthy();
    // duplicates and skipped are visible
    expect(screen.getByText("A-0001")).toBeTruthy();
    expect(screen.getByText(/no company, email or phone/)).toBeTruthy();
    expect(screen.getByText(/3 to add · 1 already present · 1 skipped/)).toBeTruthy();
  });

  it("confirms once, sends the fingerprint and idempotency key, and shows what was imported", async () => {
    const commit = vi.fn().mockResolvedValue({ outcome: "done", written: 3, already_present: 0, lead_ids: ["A-0002", "A-0003", "A-0004"] });
    const { onImported } = await previewed(commit);
    fireEvent.click(screen.getByRole("button", { name: /Import 3 leads/ }));
    await screen.findByText(/Imported 3 leads \(A-0002, A-0003, A-0004\)/);
    expect(commit).toHaveBeenCalledWith("A", PREVIEW.accepted.map((a) => a.row), "fp123", expect.any(String), { resume: false });
    expect(onImported).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: /Import 3 leads/ })).toBeNull();  // cannot press twice
    expect(screen.getByRole("link", { name: /View the leads/ }).getAttribute("href")).toBe("#/leads");
  });

  it("a stale preview is refused and must be redone before anything is written", async () => {
    const commit = vi.fn().mockRejectedValue(new ImportError("The preview is out of date. Preview again.", { stale: true }));
    await previewed(commit);
    fireEvent.click(screen.getByRole("button", { name: /Import 3 leads/ }));
    await screen.findByText(/out of date/);
    expect(screen.queryByText("A-0003")).toBeNull();
    expect(screen.queryByRole("button", { name: /Import 3 leads/ })).toBeNull();
  });

  it("shows an uncertain outcome without claiming nothing was written, and can check again", async () => {
    const commit = vi.fn()
      .mockResolvedValueOnce({ outcome: "uncertain", written: null, message: "The import could not be confirmed - it may or may not have saved." })
      .mockResolvedValueOnce({ outcome: "done", written: 1, already_present: 0, lead_ids: ["A-0002"] });
    await previewed(commit);
    fireEvent.click(screen.getByRole("button", { name: /Import 3 leads/ }));
    await screen.findByText(/Outcome uncertain/);
    expect(screen.getByText(/may or may not have saved/)).toBeTruthy();
    expect(screen.queryByText(/Nothing was written/)).toBeNull();  // never a false "nothing written"
    // "Check again" re-commits with the same key and reconciles
    fireEvent.click(screen.getByRole("button", { name: /Check again/ }));
    await screen.findByText(/Imported 1 lead/);
    expect(commit.mock.calls[1]![3]).toBe(commit.mock.calls[0]![3]);  // same idempotency key
  });

  it("shows a pending outcome as not completed, and resumes with the same key and resume=true", async () => {
    const commit = vi.fn()
      .mockResolvedValueOnce({ outcome: "pending", written: 0, already_present: 0, pending: 3, lead_ids: [] })
      .mockResolvedValueOnce({ outcome: "done", written: 3, already_present: 0, lead_ids: ["A-0002", "A-0003", "A-0004"] });
    await previewed(commit);
    fireEvent.click(screen.getByRole("button", { name: /Import 3 leads/ }));
    await screen.findByText(/Not finished yet/);
    expect(screen.getByText(/earlier attempt of this import/)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: /Resume this import/ }));
    await screen.findByText(/Imported 3 leads/);
    expect(commit.mock.calls[0]![4]).toEqual({ resume: false });
    expect(commit.mock.calls[1]![4]).toEqual({ resume: true });
    expect(commit.mock.calls[1]![3]).toBe(commit.mock.calls[0]![3]);  // same key
  });

  it("shows a blocked outcome (claimed by another submission), never as completed", async () => {
    const commit = vi.fn().mockResolvedValue({ outcome: "blocked", written: 0, already_present: 0, claimed_elsewhere: 3, lead_ids: [] });
    await previewed(commit);
    fireEvent.click(screen.getByRole("button", { name: /Import 3 leads/ }));
    await screen.findByText(/Being imported elsewhere/);
    expect(screen.getByText(/being imported by another submission/)).toBeTruthy();
    expect(screen.queryByText(/^Imported/)).toBeNull();
  });
});
