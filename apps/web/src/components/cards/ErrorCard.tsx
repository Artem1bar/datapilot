import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ErrorCardPayload } from "@/types";

interface Props {
  payload: ErrorCardPayload;
  onAction?: (action: string, data?: unknown) => void;
}

/**
 * Surfaces a failed action (plan / apply / export) as a card instead of plain
 * chat text, with an optional "Try again" button that re-dispatches the failed
 * action through the same `onAction` handler.
 */
export function ErrorCard({ payload, onAction }: Props) {
  const { title, message, retry } = payload;

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-rose-200 bg-rose-50/40 shadow-sm overflow-hidden">
        <div className="flex items-start gap-3 px-4 py-3">
          <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-rose-100 text-rose-600">
            <AlertCircle className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">{title}</p>
            <p className="mt-0.5 break-words text-[12px] text-rose-700">{message}</p>
          </div>
        </div>

        {retry && (
          <div className="flex border-t border-rose-200 bg-[var(--surface-primary)] px-4 py-3">
            <Button
              size="sm"
              variant="outline"
              className="border-rose-300 text-rose-700 transition-all duration-150 hover:bg-rose-50 active:scale-[0.98]"
              onClick={() => onAction?.(retry.action, retry.data)}
            >
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              {retry.label ?? "Try again"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
