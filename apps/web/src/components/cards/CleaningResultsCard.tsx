import { Download, BarChart3, Sparkles, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CleaningResultsPayload } from "@/types";

interface Props {
  payload: CleaningResultsPayload;
  onAction?: (action: string, data?: unknown) => void;
}

export function CleaningResultsCard({ payload, onAction }: Props) {
  const { downloadUrl, rowsBefore, rowsAfter, issuesResolved, remediationApplied } = payload;

  const rowsRemoved = rowsBefore - rowsAfter;

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-teal-200 bg-teal-50/30 shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-teal-200 bg-teal-50 px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-teal-100 text-teal-600">
            <Sparkles className="h-4 w-4" />
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[13px] font-semibold text-ink">Cleaning Complete</p>
            <p className="text-[12px] text-teal-700">
              {remediationApplied
                ? "Verified + auto-remediated by AI agent"
                : "All steps passed validation"}
            </p>
          </div>
          {remediationApplied && (
            <div className="flex items-center gap-1 rounded-full bg-brand-100 px-2 py-0.5">
              <RefreshCw className="h-3 w-3 text-brand-600" />
              <span className="text-[10px] font-medium text-brand-700">AI fixed</span>
            </div>
          )}
        </div>

        {/* Stats */}
        <div className="grid grid-cols-3 gap-px bg-teal-200/50">
          {[
            { label: "Rows before", value: rowsBefore.toLocaleString() },
            { label: "Rows after", value: rowsAfter.toLocaleString() },
            { label: "Issues fixed", value: issuesResolved.toLocaleString() },
          ].map(({ label, value }) => (
            <div key={label} className="bg-[var(--surface-primary)] px-4 py-3 text-center">
              <p className="text-[18px] font-bold text-ink">{value}</p>
              <p className="text-[11px] text-ink-muted">{label}</p>
            </div>
          ))}
        </div>

        {rowsRemoved > 0 && (
          <div className="border-t border-teal-200 px-4 py-2">
            <p className="text-[12px] text-ink-muted">
              {rowsRemoved} row{rowsRemoved !== 1 ? "s" : ""} removed during cleaning
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 border-t border-teal-200 bg-[var(--surface-primary)] px-4 py-3">
          {downloadUrl && (
            <Button
              size="sm"
              className="bg-brand-600 text-white hover:bg-brand-700 transition-all duration-150 active:scale-[0.98]"
              onClick={() => onAction?.("download", downloadUrl)}
            >
              <Download className="mr-1.5 h-3.5 w-3.5" />
              Download cleaned data
            </Button>
          )}
          <Button
            variant="outline"
            size="sm"
            className="transition-all duration-150 active:scale-[0.98]"
            onClick={() => onAction?.("analyze", payload.datasetId)}
          >
            <BarChart3 className="mr-1.5 h-3.5 w-3.5" />
            Analyze
          </Button>
        </div>
      </div>
    </div>
  );
}
