import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { CallError } from "../api";
import type { PlaybookSelection, PlaybookUpload } from "../types";
import { Playbook } from "./Playbook";

afterEach(cleanup);

const UPLOAD: PlaybookUpload = {
  kind: "docx",
  text: "## Initial email\nHi [FIRST_NAME],\n\n[CTA_QUESTION]\n\nBest,",
  review_token: "rev-xyz",
  review: {
    content_hash: "abc12345def",
    length: 50,
    initial_email: { present: true, paragraphs: ["[CTA_QUESTION]"] },
    follow_ups: { "1": { present: true, paragraphs: [] }, "2": { present: false, paragraphs: [] } },
    timing: { stated: true, business_days: [3], note: "follow-up timing: 3 business day(s)" },
    offer_values: { CTA_QUESTION: "Would next week work?" },
    missing: ['follow-up 2 is missing from the handbook'],
    ambiguous: [],
    usable_for_followups: false,
  },
};

const SELECTION: PlaybookSelection = { content_hash: "abc12345def", selection_token: "sel-xyz" };

function pickFile() {
  const input = screen.getByLabelText("Playbook file");
  fireEvent.change(input, { target: { files: [new File(["x"], "playbook.docx")] } });
}

describe("the playbook page", () => {
  it("reviews an upload, shows the sections and text, then explicitly selects and previews", async () => {
    const review = vi.fn().mockResolvedValue(UPLOAD);
    const select = vi.fn().mockResolvedValue(SELECTION);
    const preview = vi.fn().mockResolvedValue({
      step: 1, content_hash: "abc12345def", body: "Hi Dana,\n\nFollowing up …", problems: [],
    });
    render(<Playbook review={review} select={select} preview={preview} />);
    pickFile();
    await vi.waitFor(() => expect(screen.getByText(/Initial email found/)).toBeTruthy());
    expect(screen.getByText(/Follow-up 2 missing/)).toBeTruthy();
    expect(screen.getByText(/follow-up 2 is missing/)).toBeTruthy(); // the missing list
    expect(screen.getByText(/## Initial email/)).toBeTruthy(); // extracted text shown as data

    // Select is an explicit server step: it exchanges the review token for a selection token.
    fireEvent.click(screen.getByRole("button", { name: /Select this version \(abc12345\)/ }));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /Preview follow-up 1/ })).toBeTruthy());
    expect(select).toHaveBeenCalledWith({ text: UPLOAD.text, review_token: "rev-xyz" });

    fireEvent.change(screen.getByLabelText(/Recipient first name/), { target: { value: "Dana" } });
    fireEvent.click(screen.getByRole("button", { name: /Preview follow-up 1/ }));
    await vi.waitFor(() => expect(screen.getByText(/Following up/)).toBeTruthy());
    // The preview uses the SELECTION token from /select, never the review token.
    expect(preview).toHaveBeenCalledWith({ text: UPLOAD.text, selection_token: "sel-xyz", first_name: "Dana" });
  });

  it("shows a clear error when the file is rejected", async () => {
    const review = vi.fn().mockRejectedValue(new CallError("upload a PDF or a DOCX file."));
    render(<Playbook review={review} select={vi.fn()} preview={vi.fn()} />);
    pickFile();
    await vi.waitFor(() => expect(screen.getByText("upload a PDF or a DOCX file.")).toBeTruthy());
    expect(screen.queryByText(/What I found/)).toBeNull();
  });

  it("shows the server's message when selection is refused (reviewed-but-changed version)", async () => {
    const review = vi.fn().mockResolvedValue(UPLOAD);
    const select = vi.fn().mockRejectedValue(
      new CallError("This version has not been reviewed, or the review changed or expired."));
    render(<Playbook review={review} select={select} preview={vi.fn()} />);
    pickFile();
    await vi.waitFor(() => expect(screen.getByText(/Initial email found/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Select this version/ }));
    await vi.waitFor(() => expect(screen.getByText(/review changed or expired/)).toBeTruthy());
    expect(screen.queryByRole("button", { name: /Preview follow-up 1/ })).toBeNull();
  });

  it("shows the server's message when the preview is refused after selection", async () => {
    const review = vi.fn().mockResolvedValue(UPLOAD);
    const select = vi.fn().mockResolvedValue(SELECTION);
    const preview = vi.fn().mockRejectedValue(
      new CallError("This playbook was not selected, or the selection changed or expired."));
    render(<Playbook review={review} select={select} preview={preview} />);
    pickFile();
    await vi.waitFor(() => expect(screen.getByText(/Initial email found/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Select this version/ }));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /Preview follow-up 1/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Preview follow-up 1/ }));
    await vi.waitFor(() => expect(screen.getByText(/selection changed or expired/)).toBeTruthy());
  });

  it("lists why a version cannot produce a follow-up", async () => {
    const review = vi.fn().mockResolvedValue(UPLOAD);
    const select = vi.fn().mockResolvedValue(SELECTION);
    const preview = vi.fn().mockResolvedValue({
      step: 1, content_hash: "abc12345def", body: null, problems: ["follow-up 1 is missing from the handbook"],
    });
    render(<Playbook review={review} select={select} preview={preview} />);
    pickFile();
    await vi.waitFor(() => expect(screen.getByText(/Initial email found/)).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Select this version/ }));
    await vi.waitFor(() => expect(screen.getByRole("button", { name: /Preview follow-up 1/ })).toBeTruthy());
    fireEvent.click(screen.getByRole("button", { name: /Preview follow-up 1/ }));
    await vi.waitFor(() => expect(screen.getByText(/cannot produce a follow-up yet/)).toBeTruthy());
    expect(screen.getByText(/follow-up 1 is missing/)).toBeTruthy();
  });
});
