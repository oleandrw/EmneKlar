// «Jobbhistorikk» under Rapporter: the stored history of analyses and other background jobs for the course. The
// compact «Analysestatus» panel links here – tidying the panel («Skjul», «Fjern fullførte») never changes this list.
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useLocation } from "react-router";

import { api } from "../../core/api/client";
import type { Job } from "../../core/api/types";
import { formatDateTime } from "../../core/format";
import { describeJob, jobName } from "../../core/jobs-model";
import { Alert, Badge, Card, DataTable, Spinner, type Column } from "../../design-system";

const HISTORY_LIMIT = 50;
const TONE: Record<string, "info" | "neutral" | "success" | "danger" | "warning"> = {
  running: "info", stopping: "info", paused: "neutral", waiting: "neutral", completed: "success", failed: "danger",
  interrupted: "warning", cancelled: "warning",
};

export function JobHistory({ courseId }: { courseId: string }) {
  const { hash } = useLocation();
  const ref = useRef<HTMLDivElement>(null);
  const history = useQuery({
    queryKey: ["jobs", "history", "course", courseId],
    queryFn: () => api.get<{ jobs: Job[] }>(`/api/jobs/history?course_id=${encodeURIComponent(courseId)}&limit=${HISTORY_LIMIT}`),
  });
  // «Jobbhistorikk» in the status panel links to /rapporter#jobbhistorikk.
  useEffect(() => {
    if (hash === "#jobbhistorikk" && history.data) ref.current?.scrollIntoView({ block: "start" });
  }, [hash, history.data]);

  const columns: Column<Job>[] = [
    { key: "job", header: "Jobb", rowHeader: true, cell: (job) => jobName(job) },
    {
      key: "status", header: "Status", cell: (job) => {
        const d = describeJob({ ...job, progress: job.progress ?? {} } as Job);
        return <Badge tone={TONE[d.state] ?? "neutral"}>{d.status}</Badge>;
      },
    },
    { key: "started", header: "Startet", cell: (job) => formatDateTime(job.started_at ?? job.created_at) },
    { key: "finished", header: "Ferdig", cell: (job) => (job.finished_at ? formatDateTime(job.finished_at) : "–") },
    {
      key: "result", header: "Resultat eller årsak", cell: (job) => {
        const d = describeJob({ ...job, progress: job.progress ?? {} } as Job);
        return <span className="ek-small">{d.state === "running" || d.state === "waiting" || d.state === "paused" ? d.button : d.activity}</span>;
      },
    },
  ];

  return (
    <div id="jobbhistorikk" ref={ref}>
      <Card title="Jobbhistorikk" headingLevel={2}
        description={`Analyser og andre bakgrunnsjobber for dette emnet, nyeste først (de siste ${HISTORY_LIMIT}). «Skjul» og «Fjern fullførte» i Analysestatus endrer ikke denne listen.`}>
        {history.isPending ? <Spinner label="Henter jobbhistorikken …" /> : history.error ? (
          <Alert tone="danger" role="alert">{(history.error as Error).message}</Alert>
        ) : (
          <DataTable caption="Jobbhistorikk" captionHidden columns={columns} rows={history.data?.jobs ?? []}
            rowKey={(job) => job.id} empty="Ingen jobber for dette emnet ennå." />
        )}
      </Card>
    </div>
  );
}
