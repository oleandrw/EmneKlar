import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { Alert, Spinner } from "../design-system";
import { api, ApiError, onSessionExpired, setCsrfToken } from "./api/client";
import type { SessionData } from "./api/types";

const SessionContext = createContext<SessionData | null>(null);

export function useSession(): SessionData {
  const value = useContext(SessionContext);
  if (!value) throw new Error("useSession must be used inside <SessionProvider>");
  return value;
}

export function useRefreshSession(): () => Promise<void> {
  const client = useQueryClient();
  return async () => {
    await client.invalidateQueries({ queryKey: ["session"] });
  };
}

function applyAppearance(session: SessionData): () => void {
  const root = document.documentElement;
  const { theme } = session.general;
  const media = window.matchMedia("(prefers-color-scheme: dark)");
  const setTheme = () => {
    const resolved = theme === "system" ? (media.matches ? "dark" : "light") : theme;
    root.dataset.theme = resolved;
  };
  setTheme();
  root.dataset.textSize = session.appearance.text_size;
  root.dataset.density = session.appearance.density;
  root.dataset.reduceMotion = session.appearance.reduce_motion;
  root.dataset.underlineLinks = String(session.appearance.underline_links);
  if (theme === "system") {
    media.addEventListener("change", setTheme);
    return () => media.removeEventListener("change", setTheme);
  }
  return () => {};
}

export function SessionProvider({ children }: { children: ReactNode }) {
  const [expired, setExpired] = useState(false);
  const query = useQuery({
    queryKey: ["session"],
    queryFn: () => api.get<SessionData>("/api/session"),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 30_000,
  });

  useEffect(() => onSessionExpired(() => setExpired(true)), []);

  useEffect(() => {
    if (query.data) {
      setCsrfToken(query.data.csrf_token);
      return applyAppearance(query.data);
    }
    return undefined;
  }, [query.data]);

  if (expired || (query.error instanceof ApiError && query.error.status === 401)) {
    return (
      <main className="ek-shell__content" style={{ padding: "4rem 1rem", maxWidth: "40rem" }}>
        <h1>Økten er ikke gyldig</h1>
        <p className="ek-mt-4">
          Start EmneKlar med <strong>start.bat</strong> (eller snarveien). Nettleseren åpnes da automatisk med en ny
          innlogging. Lagrede data og innstillinger er ikke påvirket.
        </p>
      </main>
    );
  }
  if (query.isPending) {
    return (
      <main style={{ padding: "4rem", display: "grid", placeItems: "center" }}>
        <Spinner label="Starter EmneKlar …" />
      </main>
    );
  }
  if (query.error || !query.data) {
    return (
      <main style={{ padding: "4rem 1rem", maxWidth: "40rem", margin: "0 auto" }}>
        <h1>Fikk ikke kontakt med EmneKlar</h1>
        <div className="ek-mt-4">
          <Alert tone="danger" role="alert" title="Tilkoblingen feilet">
            {query.error instanceof Error ? query.error.message : "Ukjent feil."} Kontroller at vinduet til EmneKlar
            fortsatt er åpent, og last siden på nytt.
          </Alert>
        </div>
      </main>
    );
  }
  return <SessionContext.Provider value={query.data}>{children}</SessionContext.Provider>;
}
