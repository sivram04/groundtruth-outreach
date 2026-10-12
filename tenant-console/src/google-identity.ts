// Thin wrapper around Google Identity Services' "Sign in with Google" button. The client id is
// public (unlike the OAuth client secret, never sent to the browser) and comes from the backend
// at runtime (GET /api/config) rather than being baked in at build time, so the same build works
// whichever OAuth client the deployment is configured with.

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize(config: { client_id: string; callback: (response: { credential: string }) => void }): void;
          renderButton(parent: HTMLElement, options: { theme: string; size: string; width?: number }): void;
        };
      };
    };
  }
}

let scriptLoading: Promise<void> | null = null;

function loadScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  if (scriptLoading) return scriptLoading;
  scriptLoading = new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = "https://accounts.google.com/gsi/client";
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error("Google Sign-In could not be loaded."));
    document.head.appendChild(script);
  });
  return scriptLoading;
}

export async function renderSignInButton(
  clientId: string,
  container: HTMLElement,
  onCredential: (credential: string) => void,
): Promise<void> {
  await loadScript();
  if (!window.google?.accounts?.id) throw new Error("Google Sign-In is unavailable.");
  window.google.accounts.id.initialize({
    client_id: clientId,
    callback: (response) => onCredential(response.credential),
  });
  window.google.accounts.id.renderButton(container, { theme: "outline", size: "large", width: 280 });
}
