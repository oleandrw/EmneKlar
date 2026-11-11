// «Avslutt EmneKlar». EmneKlar runs on this machine without a window of its own – the browser is the user interface –
// so the program is stopped from here: a confirmation, a warning when jobs are running, and then a page that says
// the program has stopped (this tab can no longer reach it). Closing the browser tab does not stop EmneKlar.
import { useMutation } from "@tanstack/react-query";
import { useState } from "react";

import { Alert, ConfirmDialog } from "../design-system";
import { api, ApiError } from "./api/client";

const stoppedListeners = new Set<() => void>();

/** For the session provider: shows «EmneKlar er avsluttet» instead of the app once the program has been stopped. */
export function onAppStopped(listener: () => void): () => void {
  stoppedListeners.add(listener);
  return () => {
    stoppedListeners.delete(listener);
  };
}

const jobsRunning = (error: unknown): error is ApiError => error instanceof ApiError && error.code === "jobs_running";

export function QuitDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  // Set when EmneKlar answered that jobs are running: the next click stops it anyway.
  const [warning, setWarning] = useState<string | null>(null);
  const quit = useMutation({
    mutationFn: (force: boolean) => api.post("/api/system/shutdown", { force }),
    onSuccess: () => stoppedListeners.forEach((listener) => listener()),
    onError: (error) => {
      if (jobsRunning(error)) setWarning(error.message);
    },
  });
  const close = () => {
    setWarning(null);
    quit.reset();
    onClose();
  };
  const failure = quit.error && !jobsRunning(quit.error) ? quit.error : null;
  return (
    <ConfirmDialog open={open} onClose={close} onConfirm={() => quit.mutate(warning !== null)}
      title="Avslutte EmneKlar?" confirmLabel={warning ? "Avslutt likevel" : "Avslutt EmneKlar"}
      danger={warning !== null} loading={quit.isPending}>
      <p>
        EmneKlar stopper på denne maskinen, og denne siden mister kontakten. Du starter programmet igjen fra
        Start-menyen eller skrivebordet. Data og innstillinger beholdes, og ingenting endres i Canvas.
      </p>
      {warning ? <Alert tone="warning" title="Jobber kjører">{warning}</Alert> : null}
      {failure ? <Alert tone="danger" role="alert">{failure.message}</Alert> : null}
    </ConfirmDialog>
  );
}
