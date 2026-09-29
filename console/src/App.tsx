import { useCallback, useEffect, useState } from "react";
import { LoadError, loadSnapshot } from "./api";
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

export function App({ load = loadSnapshot }: { load?: () => Promise<Snapshot> }) {
  const route = useRoute();
  const [state, setState] = useState<State>({ data: null, error: null, loading: true });

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
  return (
    <Layout
      page={route.page}
      signedInAs={data?.signed_in_as ?? ""}
      readAt={data?.read_at ?? ""}
      refreshing={loading}
      onRefresh={refresh}
    >
      {data ? (
        <>
          {error && (
            <p className="warn" role="alert">
              Could not refresh: {error.message} What is shown was read at {data.read_at}.
            </p>
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
