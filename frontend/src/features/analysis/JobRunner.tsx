// The status of a background job started on a feature page: one compact line (or the reason, when it stopped). The
// full progress is in «Analysestatus» at the top right – the line reads the same job status, so they always agree.
import { Ban, CircleCheck, CircleDashed } from "lucide-react";
import { useEffect, useRef } from "react";

import type { Job } from "../../core/api/types";
import { useJobs, useListedJob } from "../../core/jobs";
import { describeJob, isActive, newerJob } from "../../core/jobs-model";
import { Alert, Button } from "../../design-system";
import type { JobWording } from "./ProgressPanel";
import { FINAL_STATUSES, useJob } from "./useJob";

const capitalize = (text: string) => text.charAt(0).toUpperCase() + text.slice(1);

/** One line while the job runs («Lager spørsmål · 12 av 40») with a way to the full status; afterwards what happened. */
export function JobInlineStatus({ job, noun = "jobben" }: { job: Job; noun?: string }) {
  const { revealPanel } = useJobs();
  const d = describeJob(job);
  if (isActive(job)) {
    return (
      <div className="ek-job-inline">
        {/* Static: the only spinning job indicator is «Analysestatus» at the top right. */}
        <CircleDashed aria-hidden="true" />
        <span className="ek-job-inline__text">{d.button}</span>
        <Button size="sm" variant="link" onClick={revealPanel}>Vis i Analysestatus</Button>
      </div>
    );
  }
  if (job.status === "completed") {
    return (
      <p className="ek-job-inline" data-state="completed">
        <CircleCheck aria-hidden="true" />
        <span className="ek-job-inline__text">Fullført · {d.activity}</span>
      </p>
    );
  }
  if (job.status === "cancelled") {
    return (
      <p className="ek-job-inline">
        <Ban aria-hidden="true" />
        <span className="ek-job-inline__text">{d.activity}</span>
      </p>
    );
  }
  return (
    <Alert tone={job.status === "failed" ? "danger" : "warning"} role="alert"
      title={`${capitalize(noun)} ${job.status === "failed" ? "feilet" : "ble avbrutt"}`}>
      {d.activity}
    </Alert>
  );
}

export function JobRunner({ jobId, wording, onDone }: { jobId: string; wording?: JobWording; onDone?: (job: Job) => void }) {
  const query = useJob(jobId);
  const listed = useListedJob(jobId);
  const job = query.data && listed ? newerJob(query.data, listed) : (listed ?? query.data ?? null);
  const done = useRef<string | null>(null);
  const callback = useRef(onDone);
  callback.current = onDone;
  const status = job?.status;
  useEffect(() => {
    if (job && status && FINAL_STATUSES.has(status) && done.current !== job.id) {
      done.current = job.id;
      callback.current?.(job);
    }
  }, [job, status]);
  if (!job) return <p className="ek-job-inline">Starter …</p>;
  return <JobInlineStatus job={job} noun={wording?.noun} />;
}
