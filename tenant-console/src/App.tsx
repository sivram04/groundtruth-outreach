import { useCallback, useEffect, useState } from "react";
import * as api from "./api";
import { Dashboard } from "./pages/Dashboard";
import { SignIn } from "./pages/SignIn";
import type { SessionState } from "./types";

export function App() {
  const [session, setSession] = useState<SessionState | null>(null);
  const [showSignIn, setShowSignIn] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    try {
      setSession(await api.currentSession());
      setShowSignIn(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the server.");
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (error) {
    return (
      <div className="shell">
        <div className="notice notice-error">{error}</div>
      </div>
    );
  }

  if (!session) {
    return (
      <div className="shell">
        <p>Loading...</p>
      </div>
    );
  }

  if (!session.signed_in || showSignIn) {
    return <SignIn onSignedIn={load} />;
  }

  return <Dashboard session={session} refresh={load} onAddAccount={() => setShowSignIn(true)} />;
}
