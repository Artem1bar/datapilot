import { useState } from "react";
import { Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { groupOperations, type OperationCatalog, type OperationSpec } from "@/lib/plan-editor";

interface Props {
  catalog: OperationCatalog | null;
  onAdd: (spec: OperationSpec) => void;
}

/**
 * Adds a step the planner did not propose.
 *
 * Operations are grouped in the order they are meant to run, so a person
 * picking one is nudged towards where it belongs; the new step still lands at
 * the end of the plan and can be moved from there.
 */
export function AddStepPicker({ catalog, onAdd }: Props) {
  const [open, setOpen] = useState(false);
  const groups = groupOperations(catalog);

  if (!catalog) {
    return (
      <p className="text-[12px] text-ink-muted">Loading the list of operations…</p>
    );
  }

  if (!open) {
    return (
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen(true)}
        className="text-[12px]"
      >
        <Plus className="mr-1.5 h-3.5 w-3.5" />
        Add a step
      </Button>
    );
  }

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-inset)] p-3">
      <div className="mb-2 flex items-center justify-between">
        <p className="text-[12px] font-medium text-ink">Add a step</p>
        <button
          type="button"
          onClick={() => setOpen(false)}
          aria-label="Cancel adding a step"
          className="text-ink-muted hover:text-ink"
        >
          <X className="h-3.5 w-3.5" />
        </button>
      </div>

      <div className="max-h-56 space-y-2.5 overflow-y-auto">
        {groups.map(({ group, operations }) => (
          <div key={group}>
            <p className="mb-1 text-[10px] font-semibold uppercase tracking-wide text-ink-muted">
              {group}
            </p>
            <div className="grid gap-1 sm:grid-cols-2">
              {operations.map((spec) => (
                <button
                  key={spec.name}
                  type="button"
                  onClick={() => {
                    onAdd(spec);
                    setOpen(false);
                  }}
                  title={spec.summary}
                  className="rounded border border-[var(--line)] bg-[var(--surface-primary)] px-2 py-1 text-left text-[12px] text-ink transition-colors hover:border-brand-500 hover:bg-brand-50/50"
                >
                  {spec.label}
                  {spec.destructive && (
                    <span className="ml-1 text-[10px] text-amber-600">removes data</span>
                  )}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
