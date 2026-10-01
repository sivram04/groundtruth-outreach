import { describe, expect, it } from "vitest";
import type { Lead, Snapshot } from "../types";
import { postCallReloadKey } from "./LeadPage";

// Minimal shapes; only the fields postCallReloadKey reads matter.
function lead(over: Partial<Lead> = {}): Lead {
  return {
    id: "A-0002", call_history: [{ when: "", what: "No answer", note: "" }],
    call_effect: "CONTINUE", call_task: null, suppressed: false,
    ...over,
  } as unknown as Lead;
}

function snap(over: Partial<Snapshot> = {}): Snapshot {
  return {
    approvals: { offer: true } as Snapshot["approvals"],
    links: { sheet: "", handbook: "https://docs/doc-1/edit", gmail_account: "" },
    ...over,
  } as unknown as Snapshot;
}

describe("postCallReloadKey", () => {
  it("changes when suppression flips (an external opt-out), with the call fields unchanged", () => {
    const base = postCallReloadKey(lead(), snap());
    expect(postCallReloadKey(lead({ suppressed: true }), snap())).not.toBe(base);
    expect(postCallReloadKey(lead({ suppressed: null }), snap())).not.toBe(base);
  });

  it("changes when offer approval or the handbook changes", () => {
    const base = postCallReloadKey(lead(), snap());
    expect(postCallReloadKey(lead(), snap({ approvals: { offer: false } as Snapshot["approvals"] }))).not.toBe(base);
    expect(
      postCallReloadKey(lead(), snap({ links: { sheet: "", handbook: "https://docs/doc-2/edit", gmail_account: "" } })),
    ).not.toBe(base);
  });

  it("changes when the call state changes", () => {
    const base = postCallReloadKey(lead(), snap());
    expect(postCallReloadKey(lead({ call_effect: "STOP" }), snap())).not.toBe(base);
    expect(
      postCallReloadKey(lead({ call_history: [{ when: "", what: "No answer", note: "" }, { when: "", what: "Do not contact", note: "" }] }), snap()),
    ).not.toBe(base);
  });

  it("is stable when nothing the candidate depends on changes", () => {
    expect(postCallReloadKey(lead(), snap())).toBe(postCallReloadKey(lead(), snap()));
  });
});
