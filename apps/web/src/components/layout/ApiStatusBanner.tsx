import { AlertTriangle, RefreshCw } from "lucide-react";
import { useApiStatus } from "@/hooks/use-api-status";
import type { ApiProblemKind } from "@/lib/api-base";

const TITLES: Record<ApiProblemKind, string> = {
  missing: "Backend not connected",
  unreachable: "Backend unreachable",
  blocked: "Backend blocked by this page's security policy",
};

/**
 * Says up front when the API is not there, instead of letting the first
 * upload discover it. Renders nothing while checking or when the API answers.
 */
export function ApiStatusBanner() {
  const { status, recheck } = useApiStatus();
  if (status.state !== "problem") return null;

  return (
    <div
      role="alert"
      className="flex items-start gap-3 border-b border-gold-400/40 bg-gold-50 px-4 py-2.5 text-[13px] text-ink"
    >
      <AlertTriangle
        className="mt-0.5 h-4 w-4 shrink-0 text-gold-600"
        aria-hidden="true"
      />
      <div className="min-w-0 flex-1">
        <p className="font-medium">{TITLES[status.kind]}</p>
        <p className="mt-0.5 break-words text-ink-secondary">{status.message}</p>
      </div>
      <button
        type="button"
        onClick={recheck}
        className="flex shrink-0 items-center gap-1.5 rounded-md border border-[var(--line)] bg-[var(--surface-primary)] px-2.5 py-1 text-[12px] font-medium text-ink transition-colors hover:bg-brand-50"
      >
        <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
        Retry
      </button>
    </div>
  );
}
