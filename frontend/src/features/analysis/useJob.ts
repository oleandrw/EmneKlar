// Live job state via Server-Sent Events, with polling as a fallback.
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api } from "../../core/api/client";
import type { Job } from "../../core/api/types";

export const FINAL_STATUSES = new Set(["completed", "failed", "cancelled", "interrupted"]);

export function useJob(jobId: string | null) {
  const client = useQueryClient();
  const [sseFailed, setSseFailed] = useState(false);
  const query = useQuery({
    queryKey: ["jobs", jobId],
    queryFn: () => api.get<Job>(`/api/jobs/${jobId}`),
    enabled: Boolean(jobId),
    refetchInterval: (q) =>
      sseFailed && q.state.data && !FINAL_STATUSES.has(q.state.data.status) ? 1500 : false,
  });

  useEffect(() => {
    if (!jobId || typeof EventSource === "undefined") {
      setSseFailed(true);
      return;
    }
    const source = new EventSource(`/api/jobs/${jobId}/events`);
    source.addEventListener("job", (event) => {
      const job = JSON.parse((event as MessageEvent<string>).data) as Job;
      client.setQueryData(["jobs", jobId], job);
      if (FINAL_STATUSES.has(job.status)) {
        source.close();
        void client.invalidateQueries({ queryKey: ["jobs", "active"] });
      }
    });
    source.onerror = () => {
      source.close();
      setSseFailed(true);
    };
    return () => source.close();
  }, [jobId, client]);

  return query;
}

export function jobAction(jobId: string, action: "pause" | "resume" | "cancel") {
  return api.post<Job>(`/api/jobs/${jobId}/${action}`);
}
