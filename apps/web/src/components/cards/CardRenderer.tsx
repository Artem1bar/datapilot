import type { CardPayload } from "@/types";
import { InspectionSummaryCard } from "./InspectionSummaryCard";
import { CleaningPlanCard } from "./CleaningPlanCard";
import { CleaningProgressCard } from "./CleaningProgressCard";
import { ValidationSummaryCard } from "./ValidationSummaryCard";
import { CleaningResultsCard } from "./CleaningResultsCard";
import { ManipulationPreviewCard } from "./ManipulationPreviewCard";
import { ManipulationResultCard } from "./ManipulationResultCard";
import { DataPreviewCard } from "./DataPreviewCard";
import { DataDictionaryCard } from "./DataDictionaryCard";
import { ComparisonCard } from "./ComparisonCard";
import { HistoryCard } from "./HistoryCard";
import { ErrorCard } from "./ErrorCard";

interface CardRendererProps {
  payload: CardPayload;
  messageId?: string;
  onAction?: (action: string, data?: unknown) => void;
}

/**
 * Dispatches a CardPayload to the appropriate card component.
 */
export function CardRenderer({ payload, messageId, onAction }: CardRendererProps) {
  switch (payload.type) {
    case "inspection_summary":
      return <InspectionSummaryCard payload={payload} />;

    case "cleaning_plan":
      return <CleaningPlanCard payload={payload} messageId={messageId} onAction={onAction} />;

    case "cleaning_progress":
      return <CleaningProgressCard payload={payload} />;

    case "validation_summary":
      return <ValidationSummaryCard payload={payload} />;

    case "cleaning_results":
      return <CleaningResultsCard payload={payload} onAction={onAction} />;

    case "manipulation_preview":
      return <ManipulationPreviewCard payload={payload} onAction={onAction} />;

    case "manipulation_result":
      return <ManipulationResultCard payload={payload} onAction={onAction} />;

    case "data_preview":
      return <DataPreviewCard payload={payload} onAction={onAction} />;

    case "data_dictionary":
      return <DataDictionaryCard payload={payload} />;

    case "comparison":
      return <ComparisonCard payload={payload} />;

    case "history":
      return <HistoryCard payload={payload} />;

    case "error":
      return <ErrorCard payload={payload} onAction={onAction} />;

    // Phase 3: visualization, report, data_overview cards
    default:
      return (
        <div className="my-2 max-w-[85%]">
          <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] p-4 shadow-sm">
            <div className="flex items-center gap-2 text-[12px] font-medium uppercase tracking-wide text-ink-muted">
              <span className="h-1.5 w-1.5 rounded-full bg-brand-500" />
              {payload.type.replace(/_/g, " ")}
            </div>
          </div>
        </div>
      );
  }
}
