import { useEffect, useRef, useState } from "react";
import * as api from "../api";
import { renderSignInButton } from "../google-identity";

export function SignIn({ onSignedIn }: { onSignedIn: () => void }) {
  const container = useRef<HTMLDivElement>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { google_client_id: clientId } = await api.config();
        if (!clientId) {
          if (!cancelled) setError("Google sign-in is not configured yet on the server.");
          return;
        }
        if (container.current) {
          await renderSignInButton(clientId, container.current, async (credential) => {
            try {
              await api.signIn(credential);
              onSignedIn();
            } catch (err) {
              setError(err instanceof Error ? err.message : "Sign-in failed.");
            }
          });
        }
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not load sign-in.");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [onSignedIn]);

  return (
    <div className="shell">
      <div className="card" style={{ textAlign: "center", padding: "48px 24px" }}>
        <h1>Outreach</h1>
        <p>Sign in with Google to connect your own leads Sheet and Gmail.</p>
        {error && <div className="notice notice-error">{error}</div>}
        <div ref={container} style={{ display: "flex", justifyContent: "center", marginTop: 16 }} />
      </div>
    </div>
  );
}
