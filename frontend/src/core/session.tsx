import { useQuery, useQueryClient } from "@tanstack/react-query";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

import { Alert, Spinner } from "../design-system";
import { api, ApiError, onSessionExpired, setCsrfToken } from "./api/client";
import type { SessionData } from "./api/types";
import { announceWindow } from "./presence";
import { onAppStopped } from "./quit";

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
  const [stopped, setStopped] = useState(false);
  const query = useQuery({
    queryKey: ["session"],
    queryFn: () => api.get<SessionData>("/api/session"),
    retry: (count, error) => !(error instanceof ApiError && error.status === 401) && count < 2,
    staleTime: 30_000,
  });

  useEffect(() => onSessionExpired(() => setExpired(true)), []);
  useEffect(() => onAppStopped(() => setStopped(true)), []);
  // While this window shows EmneKlar, it keeps EmneKlar running; when the last window is closed, EmneKlar stops.
  const shown = Boolean(query.data) && !expired && !stopped;
  useEffect(() => (shown ? announceWindow() : undefined), [shown]);

  useEffect(() => {
    if (query.data) {
      setCsrfToken(query.data.csrf_token);
      return applyAppearance(query.data);
    }
    return undefined;
  }, [query.data]);

  if (stopped) {
    // «Avslutt EmneKlar» was chosen: the program no longer runs, so nothing on the page would work.
    return (
      <main className="ek-shell__content ek-message-page">
        <h1>EmneKlar er avsluttet</h1>
        <p className="ek-mt-4">
          Programmet kjører ikke lenger på denne maskinen, og du kan lukke vinduet. Start EmneKlar igjen fra
          Start-menyen eller skrivebordet. Data og innstillinger er beholdt.
        </p>
      </main>
    );
  }
  if (expired || (query.error instanceof ApiError && query.error.status === 401)) {
    return (
      <main className="ek-shell__content ek-message-page">
        <h1>Økten er ikke gyldig</h1>
        <p className="ek-mt-4">
          Start EmneKlar på nytt fra <strong>Start-menyen</strong> eller skrivebordet. EmneKlar åpnes da automatisk
          med en ny innlogging. Lagrede data og innstillinger er ikke påvirket.
        </p>
      </main>
    );
  }
  if (query.isPending) {
    return (
      <main className="ek-loading-page">
        <Spinner label="Starter EmneKlar …" />
      </main>
    );
  }
  if (query.error || !query.data) {
    return (
      <main className="ek-message-page">
        <h1>Fikk ikke kontakt med EmneKlar</h1>
        <div className="ek-mt-4">
          <Alert tone="danger" role="alert" title="Tilkoblingen feilet">
            {query.error instanceof Error ? query.error.message : "Ukjent feil."} Kontroller at EmneKlar kjører –
            start programmet fra Start-menyen eller skrivebordet – og last siden på nytt.
          </Alert>
        </div>
      </main>
    );
  }
  return <SessionContext.Provider value={query.data}>{children}</SessionContext.Provider>;
}
