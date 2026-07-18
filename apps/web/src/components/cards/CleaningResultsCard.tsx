import { useState } from "react";
import {
  Download,
  BarChart3,
  Sparkles,
  RefreshCw,
  AlertTriangle,
  GitCompare,
  BookmarkPlus,
  Undo2,
  Check,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { CleaningResultsPayload } from "@/types";

interface Props {
  payload: CleaningResultsPayload;
  messageId?: string;
  onAction?: (action: string, data?: unknown) => void;
}

export function CleaningResultsCard({ payload, messageId, onAction }: Props) {
  const {
    downloadUrl,
    rowsBefore,
    rowsAfter,
    issuesResolved,
    remediationApplied,
    unresolvableFlags,
    jobId,
    reverted,
    savedRecipeName,
  } = payload;

  const [saveOpen, setSaveOpen] = useState(false);
  const [recipeName, setRecipeName] = useState("");

  const rowsRemoved = rowsBefore - rowsAfter;
  const unresolved = unresolvableFlags ?? [];

  const handleSaveRecipe = () => {
    const name = recipeName.trim();
    if (!name || !jobId) return;
    onAction?.("save_recipe", { jobId, name, messageId });
    setSaveOpen(false);
    setRecipeName("");
  };

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
          {reverted && (
            <div className="flex items-center gap-1 rounded-full bg-amber-100 px-2 py-0.5">
              <Undo2 className="h-3 w-3 text-amber-600" />
              <span className="text-[10px] font-medium text-amber-700">Reverted</span>
            </div>
          )}
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

        {unresolved.length > 0 && (
          <div className="flex items-start gap-2 border-t border-amber-200 bg-amber-50/50 px-4 py-2">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" />
            <p className="text-[12px] text-amber-700">
              {unresolved.length} issue{unresolved.length !== 1 ? "s" : ""} couldn&apos;t be
              auto-fixed: <span className="font-mono">{unresolved.join(", ")}</span>
            </p>
          </div>
        )}

        {/* Actions */}
        <div className="flex flex-wrap gap-2 border-t border-teal-200 bg-[var(--surface-primary)] px-4 py-3">
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
          {jobId && (
            <Button
              variant="outline"
              size="sm"
              className="transition-all duration-150 active:scale-[0.98]"
              onClick={() => onAction?.("compare_cleaning", { jobId })}
            >
              <GitCompare className="mr-1.5 h-3.5 w-3.5" />
              See what changed
            </Button>
          )}
          {jobId &&
            (savedRecipeName ? (
              <span className="inline-flex items-center gap-1.5 px-2 py-1 text-[12px] text-teal-700">
                <Check className="h-3.5 w-3.5" />
                Saved as &ldquo;{savedRecipeName}&rdquo;
              </span>
            ) : (
              <Button
                variant="outline"
                size="sm"
                className="transition-all duration-150 active:scale-[0.98]"
                onClick={() => setSaveOpen(true)}
              >
                <BookmarkPlus className="mr-1.5 h-3.5 w-3.5" />
                Save as recipe
              </Button>
            ))}
          {jobId && !reverted && (
            <Button
              variant="ghost"
              size="sm"
              className="text-ink-muted hover:text-red-600 transition-all duration-150 active:scale-[0.98]"
              onClick={() => onAction?.("revert_cleaning", { jobId, messageId })}
            >
              <Undo2 className="mr-1.5 h-3.5 w-3.5" />
              Revert to original
            </Button>
          )}
        </div>
      </div>

      {/* Save-as-recipe dialog */}
      <Dialog open={saveOpen} onOpenChange={setSaveOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Save as recipe</DialogTitle>
            <DialogDescription>
              Save this cleaning plan as a reusable template you can apply to other datasets from
              the <span className="font-medium">+</span> menu.
            </DialogDescription>
          </DialogHeader>
          <Input
            placeholder="e.g. Standard orders cleanup"
            value={recipeName}
            onChange={(e) => setRecipeName(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSaveRecipe();
            }}
            autoFocus
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setSaveOpen(false)}>
              Cancel
            </Button>
            <Button
              className="bg-brand-600 text-white hover:bg-brand-700"
              onClick={handleSaveRecipe}
              disabled={!recipeName.trim()}
            >
              Save recipe
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
