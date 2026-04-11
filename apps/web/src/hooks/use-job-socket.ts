import { useEffect, useRef, useState, useCallback } from "react";
import { api } from "@/lib/api";
import type { JobStatus } from "@/types";

export interface JobProgress {
  job_id: string;
  status: JobStatus;
  progress: number;
  message?: string;
  result?: unknown;
}

interface UseJobSocketOptions {
  jobId: string | null;
  onComplete?: (jobId: string, result?: unknown) => void;
  onError?: (jobId: string, error: string) => void;
}

/** Maps the WS / poll payload into our internal state. */
function toJobProgress(data: Record<string, unknown>): JobProgress {
  return {
    job_id: data.job_id as string,
    status: data.status as JobStatus,
    progress: (data.progress as number) ?? 0,
    message: data.message as string | undefined,
    result: data.result,
  };
}

export function useJobSocket({
  jobId,
  onComplete,
  onError,
}: UseJobSocketOptions) {
  const [progress, setProgress] = useState<JobProgress | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const onCompleteRef = useRef(onComplete);
  const onErrorRef = useRef(onError);

  onCompleteRef.current = onComplete;
  onErrorRef.current = onError;

  const cleanup = useCallback(() => {
    if (wsRef.current) {
      wsRef.current.close();
      wsRef.current = null;
    }
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  /** Handle an incoming progress payload (from WS or polling). */
  const handlePayload = useCallback((data: JobProgress) => {
    setProgress(data);

    if (data.status === "completed") {
      onCompleteRef.current?.(data.job_id, data.result);
    } else if (data.status === "failed") {
      onErrorRef.current?.(data.job_id, data.message ?? "Unknown error");
    }
  }, []);

  /** Start polling GET /api/v1/jobs/{jobId} every 2 seconds as fallback. */
  const startPolling = useCallback(
    (id: string) => {
      if (pollingRef.current) return; // already polling

      const poll = async () => {
        try {
          const data = await api.get(`jobs/${id}`).json<Record<string, unknown>>();
          const mapped = toJobProgress(data);
          handlePayload(mapped);

          // Stop polling once terminal
          if (mapped.status === "completed" || mapped.status === "failed") {
            if (pollingRef.current) {
              clearInterval(pollingRef.current);
              pollingRef.current = null;
            }
          }
        } catch {
          // Silently retry on next interval
        }
      };

      // Fire immediately, then every 2 s
      void poll();
      pollingRef.current = setInterval(() => void poll(), 2000);
    },
    [handlePayload],
  );

  useEffect(() => {
    if (!jobId) {
      setProgress(null);
      return;
    }

    // Build WS URL: /ws/jobs/{job_id}
    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const wsUrl = `${protocol}//${window.location.host}/ws/jobs/${jobId}`;

    try {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.addEventListener("message", (event: MessageEvent) => {
        const data = JSON.parse(event.data as string) as Record<string, unknown>;
        handlePayload(toJobProgress(data));
      });

      ws.addEventListener("error", () => {
        // WebSocket failed — fall back to polling
        ws.close();
        wsRef.current = null;
        startPolling(jobId);
      });

      ws.addEventListener("close", () => {
        wsRef.current = null;
        // If not yet terminal, start polling as fallback
        const current = progress;
        if (
          !current ||
          (current.status !== "completed" && current.status !== "failed")
        ) {
          startPolling(jobId);
        }
      });
    } catch {
      // WebSocket construction failed (e.g. bad URL) — fall back to polling
      startPolling(jobId);
    }

    return cleanup;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jobId]);

  return { progress, disconnect: cleanup };
}
