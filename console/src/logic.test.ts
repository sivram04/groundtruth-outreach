import { afterEach, describe, expect, it, vi } from "vitest";
import { EXPECTED_VERSION, LoadError, loadSnapshot } from "./api";
import demo from "./demo/snapshot.json";
import { SHOW, filterLeads, readFilter } from "./filters";
import { gmailSearch, plural, safeHref } from "./format";
import { href, leadHref, parse } from "./router";
import type { Snapshot } from "./types";

const data = demo as unknown as Snapshot;

describe("the pages' addresses", () => {
  it("reads each page from the part after the #", () => {
    expect(parse("").page).toBe("dashboard");
    expect(parse("#/").page).toBe("dashboard");
    expect(parse("#/drafts").page).toBe("drafts");
    expect(parse("#/sources").page).toBe("sources");
    expect(parse("#/leads").page).toBe("leads");
    expect(parse("#/leads/A-0001")).toMatchObject({ page: "lead", id: "A-0001" });
    expect(parse("#/leads/A%2D0001").id).toBe("A-0001");
    expect(parse("#/leads?show=ready&q=acme").query.get("show")).toBe("ready");
  });

  it("calls anything else missing, never a page it is not", () => {
    for (const hash of ["#/nowhere", "#/drafts/extra", "#/leads/A-1/more", "#/sources/x"]) {
      expect(parse(hash).page).toBe("missing");
    }
    expect(parse("#/leads/%E0%A4%A").id).toBe("%E0%A4%A"); // a bad escape is kept as written
  });

  it("writes links with only the filters that are set", () => {
    expect(href("/leads", { q: "", tier: "A", show: "" })).toBe("#/leads?tier=A");
    expect(href("/drafts")).toBe("#/drafts");
    expect(leadHref("A-0001")).toBe("#/leads/A-0001");
  });
});

describe("links out", () => {
  it("opens Gmail searched for the address, in the sending account", () => {
    expect(gmailSearch("sam@example-electric.test", "admin@lakshyaa.ai")).toBe(
      "https://mail.google.com/mail/u/?authuser=admin@lakshyaa.ai#search/sam@example-electric.test",
    );
    expect(gmailSearch("a b@x.test", "")).toBe("https://mail.google.com/mail/u/#search/a%20b@x.test");
  });

  it("links a website only when it is an http address", () => {
    expect(safeHref("https://example-electric.test/")).toBe("https://example-electric.test/");
    expect(safeHref("http://x.test")).toBe("http://x.test");
    for (const bad of ["javascript:alert(1)", "JavaScript:alert(1)", "data:text/html,x", "riverbend.test", ""]) {
      expect(safeHref(bad)).toBe("");
    }
  });

  it("says one or many", () => {
    expect(plural(1, "tracked email")).toBe("1 tracked email");
    expect(plural(2, "tracked email")).toBe("2 tracked emails");
  });
});

describe("the Leads filters", () => {
  const ids = (q: string, tier = "", show = "all") => filterLeads(data, { q, tier, show }).map((lead) => lead.id);

  it("narrows by search words over the id, company, contact and email", () => {
    expect(ids("acme")).toEqual(["A-0002"]);
    expect(ids("PAT LEE")).toEqual(["A-0002"]);
    expect(ids("b-000")).toEqual(["B-0001", "B-0002", "B-0003"]);
    expect(ids("nothing like this")).toEqual([]);
  });

  it("narrows by tier and by what the lead needs", () => {
    expect(ids("", "B")).toEqual(["B-0001", "B-0002", "B-0003"]);
    expect(ids("", "", "ready")).toEqual(["A-0007", "A-0008", "A-0013", "A-0014"]);
    expect(ids("", "", "needs")).toEqual(["A-0001", "A-0002", "A-0004", "A-0005", "B-0002"]);
    expect(ids("", "", "replied")).toEqual(["A-0002"]);
    expect(ids("", "", "stopped")).toEqual(["A-0006"]);
    expect(ids("", "", "bounced")).toEqual(["A-0005"]);
    expect(ids("", "", "check")).toEqual(["A-0004"]);
    expect(ids("", "", "emailed")).toHaveLength(7);
    expect(ids("", "", "not-emailed")).toHaveLength(12);  // incl. the phone-only and company-only leads
    expect(ids("", "A", "ready")).toEqual(["A-0007", "A-0008", "A-0013", "A-0014"]);
  });

  it("ignores a filter value it does not know", () => {
    const filter = readFilter(new URLSearchParams("show=everything&tier=Z&q=" + "x".repeat(300)), data);
    expect(filter).toEqual({ q: "x".repeat(100), tier: "", show: "all" });
    expect(SHOW.map(([key]) => key)).toContain("needs");
  });
});

describe("reading the data from the server", () => {
  afterEach(() => vi.restoreAllMocks());

  const answer = (status: number, body: unknown, type = "application/json") =>
    vi.fn().mockResolvedValue(
      new Response(typeof body === "string" ? body : JSON.stringify(body), {
        status,
        headers: { "Content-Type": type },
      }),
    );

  it("asks for the snapshot the way IAP answers with 401 instead of a sign-in page", async () => {
    const fetcher = answer(200, data);
    await expect(loadSnapshot(fetcher)).resolves.toEqual(data);
    const [url, init] = fetcher.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/snapshot");
    expect((init.headers as Record<string, string>)["X-Requested-With"]).toBe("XMLHttpRequest");
    expect(init.cache).toBe("no-store");
  });

  it("says the sign-in ended on a 401, and on a page that is not data", async () => {
    for (const fetcher of [answer(401, { error: "no sign-in token" }), answer(200, "<html>Sign in</html>", "text/html")]) {
      const error = await loadSnapshot(fetcher).catch((caught: unknown) => caught);
      expect(error).toBeInstanceOf(LoadError);
      expect((error as LoadError).signIn).toBe(true);
    }
  });

  it("passes on what the server said went wrong", async () => {
    const error = await loadSnapshot(answer(502, { error: "The Sheet could not be read just now." })).catch(
      (caught: unknown) => caught,
    );
    expect((error as LoadError).message).toBe("The Sheet could not be read just now.");
    expect((error as LoadError).signIn).toBe(false);
  });

  it("refuses data in a shape this page does not know", async () => {
    const error = await loadSnapshot(answer(200, { ...data, version: EXPECTED_VERSION + 1 })).catch(
      (caught: unknown) => caught,
    );
    expect((error as LoadError).signIn).toBe(true);
  });

  it("says so when the console cannot be reached", async () => {
    const error = await loadSnapshot(vi.fn().mockRejectedValue(new TypeError("failed"))).catch(
      (caught: unknown) => caught,
    );
    expect((error as LoadError).message).toMatch(/could not be reached/);
  });
});
