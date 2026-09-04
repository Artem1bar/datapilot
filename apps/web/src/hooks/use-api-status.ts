import { useCallback, useEffect, useState } from "react";
import {
  apiLocation,
  classifyHealth,
  describeApiProblem,
  isApiCspViolation,
  pageOrigin,
  type ApiProblemKind,
} from "@/lib/api-base";

export type ApiStatus =
  | { state: "checking" }
  | { state: "ok" }
  | { state: "problem"; kind: ApiProblemKind; message: string };

export const HEALTH_TIMEOUT_MS = 8_000;

function problem(kind: ApiProblemKind): ApiStatus {
  return {
    state: "problem",
    kind,
    message: describeApiProblem(kind, apiLocation, pageOrigin),
  };
}

/**
 * Probes the API's health check once on mount (and again on `recheck`) so a
 * deployment with no backend says so before the first upload finds out.
 */
export function useApiStatus(): { status: ApiStatus; recheck: () => void } {
  const [status, setStatus] = useState<ApiStatus>({ state: "checking" });
  const [attempt, setAttempt] = useState(0);

  const recheck = useCallback(() => {
    setStatus({ state: "checking" });
    setAttempt((n) => n + 1);
  }, []);

  useEffect(() => {
    let active = true;
    let blockedByCsp = false;
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);

    // A CSP report can land after the fetch has already failed; note it and
    // upgrade the verdict when it does.
    const onViolation = (event: Event) => {
      if (!isApiCspViolation(event as SecurityPolicyViolationEvent)) return;
      blockedByCsp = true;
      if (active) setStatus(problem("blocked"));
    };
    document.addEventListener("securitypolicyviolation", onViolation);

    void (async () => {
      try {
        const res = await fetch(apiLocation.healthUrl, {
          signal: controller.signal,
          headers: { Accept: "application/json" },
        });
        const text = await res.text();
        if (!active) return;
        const verdict = classifyHealth(
          res.status,
          res.headers.get("content-type"),
          text,
        );
        setStatus(verdict === "ok" ? { state: "ok" } : problem(verdict));
      } catch {
        if (!active) return;
        setStatus(problem(blockedByCsp ? "blocked" : "unreachable"));
      } finally {
        clearTimeout(timer);
      }
    })();

    return () => {
      active = false;
      clearTimeout(timer);
      controller.abort();
      document.removeEventListener("securitypolicyviolation", onViolation);
    };
  }, [attempt]);

  return { status, recheck };
}
