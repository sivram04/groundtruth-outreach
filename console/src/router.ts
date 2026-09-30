import { useEffect, useState } from "react";

// Pages live after the # in the address (#/leads/A-0001?show=ready), so the server only ever
// sends one page and a link to any page still works after a reload.

export type Page = "dashboard" | "drafts" | "leads" | "lead" | "review" | "sources" | "import" | "missing";

export interface Route {
  page: Page;
  id: string;
  query: URLSearchParams;
}

export function parse(hash: string): Route {
  const raw = hash.replace(/^#/, "");
  const [path = "", search = ""] = raw.split("?", 2);
  const parts = path.split("/").filter(Boolean).map((part) => {
    try {
      return decodeURIComponent(part);
    } catch {
      return part;
    }
  });
  const query = new URLSearchParams(search);
  const [first, second, ...rest] = parts;
  if (rest.length) return { page: "missing", id: "", query };
  if (!first) return { page: "dashboard", id: "", query };
  if (first === "drafts" && !second) return { page: "drafts", id: "", query };
  if (first === "sources" && !second) return { page: "sources", id: "", query };
  if (first === "import" && !second) return { page: "import", id: "", query };
  if (first === "review" && second) return { page: "review", id: second, query };
  if (first === "leads") return second ? { page: "lead", id: second, query } : { page: "leads", id: "", query };
  return { page: "missing", id: "", query };
}

/** A link to a page, e.g. href("/leads", { show: "ready" }) is "#/leads?show=ready". */
export function href(path: string, query: Record<string, string> = {}): string {
  const kept = Object.entries(query).filter(([, value]) => value !== "");
  const search = new URLSearchParams(kept).toString();
  return `#${path}${search ? `?${search}` : ""}`;
}

export function leadHref(id: string): string {
  return href(`/leads/${encodeURIComponent(id)}`);
}

export function reviewHref(id: string): string {
  return href(`/review/${encodeURIComponent(id)}`);
}

export function useRoute(): Route {
  const [route, setRoute] = useState(() => parse(window.location.hash));
  useEffect(() => {
    const changed = () => {
      setRoute(parse(window.location.hash));
      window.scrollTo?.(0, 0);
    };
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  return route;
}
