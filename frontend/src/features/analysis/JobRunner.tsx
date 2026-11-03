// Inline progress for a background job started from a feature page (not the global analysis dialog).
import { useEffect, useRef } from "react";

import type { Job } from "../../core/api/types";
import { Spinner } from "../../design-system";
import { ProgressPanel, type JobWording } from "./ProgressPanel";
import { FINAL_STATUSES, useJob } from "./useJob";

export function JobRunner({ jobId, wording, onDone }: { jobId: string; wording?: JobWording; onDone?: (job: Job) => void }) {
  const job = useJob(jobId);
  const done = useRef<string | null>(null);
  const callback = useRef(onDone);
  callback.current = onDone;
  const status = job.data?.status;
  useEffect(() => {
    if (job.data && status && FINAL_STATUSES.has(status) && done.current !== job.data.id) {
      done.current = job.data.id;
      callback.current?.(job.data);
    }
  }, [job.data, status]);
  if (!job.data) return <Spinner label="Starter …" />;
  return <ProgressPanel job={job.data} wording={wording} />;
}
