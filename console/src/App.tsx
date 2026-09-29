import { useCallback, useEffect, useMemo, useState } from "react";
import { LoadError, loadSnapshot, runningBuild, type askAssistant } from "./api";
import { Assistant } from "./assistant";
import { NAME } from "./brand";
import { Card, Layout, Warnings } from "./components";
import { Dashboard } from "./pages/Dashboard";
import { Drafts } from "./pages/Drafts";
import { LeadPage } from "./pages/LeadPage";
import { Leads } from "./pages/Leads";
import { NotFound } from "./pages/NotFound";
import { Sources } from "./pages/Sources";
import { useRoute, type Route } from "./router";
import type { Snapshot } from "./types";

interface State {
  data: Snapshot | null;
  error: LoadError | null;
  loading: boolean;
}

const TITLES: Record<string, string> = {
  dashboard: "Dashboard",
  drafts: "Drafts",
  leads: "Leads",
  sources: "Sources",
  missing: "Not found",
};

function page(route: Route, data: Snapshot) {
  switch (route.page) {
    case "dashboard":
      return <Dashboard data={data} />;
    case "drafts":
      return <Drafts data={data} />;
    case "leads":
      return <Leads key={route.query.toString()} data={data} query={route.query} />;
    case "lead":
      return <LeadPage data={data} id={route.id} />;
    case "sources":
      return <Sources data={data} />;
    default:
      return <NotFound />;
  }
}

function Failed({ error, onRetry }: { error: LoadError; onRetry: () => void }) {
  return (
    <Card title="The data could not be shown">
      <p>{error.message}</p>
      {error.signIn ? (
        <button type="button" onClick={() => window.location.reload()}>
          Reload the page
        </button>
      ) : (
        <button type="button" onClick={onRetry}>
          Try again
        </button>
      )}
    </Card>
  );
}

/** Whether the assistant is open is remembered in this browser, per person, and nowhere else. */
const ASSISTANT_KEY = "outreach.assistant";

function remembered(): boolean {
  // On a phone the assistant covers the page, so it opens only when asked for; on a wide
  // screen it sits beside the pages. Either way, what the founder last chose wins.
  const wide = typeof window.matchMedia === "function" ? window.matchMedia("(min-width: 861px)").matches : true;
  try {
    const kept = window.localStorage.getItem(ASSISTANT_KEY);
    return kept === null ? wide : kept !== "off";
  } catch {
    return wide;
  }
}

function remember(shown: boolean) {
  try {
    window.localStorage.setItem(ASSISTANT_KEY, shown ? "on" : "off");
  } catch {
    // A browser that keeps nothing is fine; the assistant simply opens again next time.
  }
}

export function App({ load = loadSnapshot, ask }: { load?: () => Promise<Snapshot>; ask?: typeof askAssistant }) {
  const route = useRoute();
  const [state, setState] = useState<State>({ data: null, error: null, loading: true });
  const [assistantShown, setAssistantShown] = useState(remembered);

  const refresh = useCallback(() => {
    setState((current) => ({ ...current, loading: true }));
    load().then(
      (data) => setState({ data, error: null, loading: false }),
      (error: unknown) =>
        setState((current) => ({
          data: current.data,
          error: error instanceof LoadError ? error : new LoadError("Something went wrong reading the Sheet. Try again."),
          loading: false,
        })),
    );
  }, [load]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const lead = route.page === "lead" ? state.data?.leads.find((item) => item.id === route.id) : undefined;
  useEffect(() => {
    const title = route.page === "lead" ? lead?.company || route.id : TITLES[route.page];
    document.title = `${NAME}: ${title}`;
  }, [route, lead]);

  const { data, error, loading } = state;
  // The server says which build of the pages it has. If this page is an older one, the founder
  // is looking at something the console has replaced, and only a reload will show it.
  const stale = Boolean(data?.build && runningBuild() && data.build !== runningBuild());
  const companies = useMemo(
    () => new Map((data?.leads ?? []).map((item) => [item.id, item.company || item.id])),
    [data],
  );
  const show = useCallback((shown: boolean) => {
    setAssistantShown(shown);
    remember(shown);
  }, []);

  return (
    <Layout
      page={route.page}
      signedInAs={data?.signed_in_as ?? ""}
      readAt={data?.read_at ?? ""}
      refreshing={loading}
      draftsWaiting={data?.drafts.length ?? 0}
      assistantShown={assistantShown}
      onAssistant={show}
      assistant={<Assistant companies={companies} ask={ask} onClose={() => show(false)} />}
      onRefresh={refresh}
    >
      {data ? (
        <>
          {stale && (
            <div className="callout blue" role="alert">
              <div className="callout-text">
                <strong>The console has been updated.</strong> This page is an older version of it.
              </div>
              <button type="button" className="small" onClick={() => window.location.reload()}>
                Reload the page
              </button>
            </div>
          )}
          {error && (
            <div className="callout amber" role="alert">
              <div className="callout-text">
                Could not refresh: {error.message} What is shown was read at {data.read_at}.
              </div>
            </div>
          )}
          <Warnings warnings={data.warnings} />
          {page(route, data)}
        </>
      ) : error ? (
        <Failed error={error} onRetry={refresh} />
      ) : (
        <p className="muted loading" role="status">
          Reading the Sheet…
        </p>
      )}
    </Layout>
  );
}
