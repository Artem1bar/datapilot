import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { ColumnChoice, ScatterColumns, ScatterRequest } from "@/lib/scatter";

/**
 * Pick two numeric columns, and optionally one to color by.
 *
 * Native selects rather than the Radix menu used in settings: a column list
 * can run to sixty entries, the browser's own control handles that with
 * type-ahead and a scrollbar, and the choice is fully keyboard- and
 * screen-reader-accessible without any extra wiring.
 */

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Null while the dataset's columns are loading. */
  columns: ScatterColumns | null;
  loadError?: string | null;
  /** The API's refusal, shown beside the form so the user can fix the choice. */
  error?: string | null;
  submitting?: boolean;
  onSubmit: (request: ScatterRequest) => void;
}

const SELECT_CLASS =
  "flex h-9 w-full rounded-md border border-[var(--line)] bg-[var(--surface-canvas)] px-2.5 text-[13px] text-ink focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-400 disabled:cursor-not-allowed disabled:opacity-50";

function Field({
  id,
  label,
  children,
}: {
  id: string;
  label: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-[12px] font-medium text-ink-secondary">
        {label}
      </label>
      {children}
    </div>
  );
}

/** What the user has chosen; anything unset falls back to a default. */
interface Choice {
  readonly x?: string;
  readonly y?: string;
  readonly colorBy?: string;
  readonly size?: string;
}

function options(columns: readonly ColumnChoice[]) {
  return columns.map((column) => (
    <option key={column.name} value={column.name}>
      {column.name}
    </option>
  ));
}

export function ScatterPlotDialog({
  open,
  onOpenChange,
  columns,
  loadError = null,
  error = null,
  submitting = false,
  onSubmit,
}: Props) {
  const [choice, setChoice] = useState<Choice>({});
  // Forget the selection each time the dialog opens, so a reopened dialog
  // does not carry a choice from another dataset. Resetting during render on
  // a prop change is React's documented pattern; an effect would paint the
  // stale choice first.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    setChoice({});
  }

  const numeric = columns?.numeric ?? [];
  const categorical = columns?.categorical ?? [];
  // The first two numeric columns, by name, are the default plot.
  const x = choice.x ?? numeric[0]?.name ?? "";
  const y = choice.y ?? numeric[1]?.name ?? "";
  const colorBy = choice.colorBy ?? "";
  const size = choice.size ?? "";
  const tooFew = columns !== null && numeric.length < 2;
  const canPlot = x !== "" && y !== "" && x !== y && !submitting && !tooFew;

  // A column plays one role: not both axes, not an axis and a color or size.
  const without = (value: string, current: string) => (value === current ? "" : current);
  const chooseX = (value: string) =>
    setChoice({
      x: value,
      y: without(value, y),
      colorBy: without(value, colorBy),
      size: without(value, size),
    });
  const chooseY = (value: string) =>
    setChoice({ x, y: value, colorBy: without(value, colorBy), size: without(value, size) });
  const chooseColor = (value: string) =>
    setChoice({ x, y, colorBy: value, size: without(value, size) });
  const chooseSize = (value: string) =>
    setChoice({ x, y, colorBy: without(value, colorBy), size: value });
  const submit = () => {
    if (!canPlot) return;
    onSubmit({ x, y, colorBy: colorBy || null, size: size || null });
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Scatter plot</DialogTitle>
          <DialogDescription>
            Plot one numeric column against another over every row, with a
            least-squares line fitted to all of them. Add a size for a bubble
            chart. No AI is involved; the numbers are computed from the data.
          </DialogDescription>
        </DialogHeader>

        {loadError ? (
          <p role="alert" className="text-[13px] text-red-600">
            {loadError}
          </p>
        ) : columns === null ? (
          <div className="flex items-center gap-2 py-4 text-[13px] text-ink-muted">
            <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
            Loading columns...
          </div>
        ) : tooFew ? (
          <p className="py-2 text-[13px] text-ink-muted">
            This dataset needs at least two numeric columns to plot.
          </p>
        ) : (
          <form
            className="space-y-3"
            onSubmit={(event) => {
              event.preventDefault();
              submit();
            }}
          >
            <div className="grid grid-cols-2 gap-3">
              <Field id="scatter-x" label="X axis">
                <select
                  id="scatter-x"
                  className={SELECT_CLASS}
                  value={x}
                  disabled={submitting}
                  onChange={(event) => chooseX(event.target.value)}
                >
                  {x === "" ? <option value="">Choose a column</option> : null}
                  {options(numeric)}
                </select>
              </Field>
              <Field id="scatter-y" label="Y axis">
                <select
                  id="scatter-y"
                  className={SELECT_CLASS}
                  value={y}
                  disabled={submitting}
                  onChange={(event) => chooseY(event.target.value)}
                >
                  <option value="">Choose a column</option>
                  {options(numeric.filter((column) => column.name !== x))}
                </select>
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <Field id="scatter-color" label="Color by">
                <select
                  id="scatter-color"
                  className={SELECT_CLASS}
                  value={colorBy}
                  disabled={submitting}
                  onChange={(event) => chooseColor(event.target.value)}
                >
                  <option value="">None</option>
                  {options(
                    categorical.filter(
                      (column) => column.name !== x && column.name !== y && column.name !== size,
                    ),
                  )}
                </select>
              </Field>
              <Field id="scatter-size" label="Bubble size">
                <select
                  id="scatter-size"
                  className={SELECT_CLASS}
                  value={size}
                  disabled={submitting}
                  onChange={(event) => chooseSize(event.target.value)}
                >
                  <option value="">None</option>
                  {options(
                    numeric.filter(
                      (column) =>
                        column.name !== x && column.name !== y && column.name !== colorBy,
                    ),
                  )}
                </select>
              </Field>
            </div>
          </form>
        )}

        {error ? (
          <p role="alert" className="text-[13px] text-red-600">
            {error}
          </p>
        ) : null}

        <DialogFooter>
          <Button variant="outline" type="button" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          {columns !== null && !loadError ? (
            <Button
              type="button"
              className="bg-brand-600 text-white hover:bg-brand-700"
              onClick={submit}
              disabled={!canPlot}
            >
              {submitting ? "Plotting..." : "Plot"}
            </Button>
          ) : null}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
