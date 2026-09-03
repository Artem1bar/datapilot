import { useCallback, useEffect, useState } from "react";
import { api } from "@/lib/api";
import { scatterColumns, type ScatterColumns, type ScatterRequest } from "@/lib/scatter";
import { useScatterPlot } from "@/hooks/use-scatter-plot";
import { useAppStore } from "@/stores/app-store";
import { useSessionStore } from "@/stores/session-store";
import type { DatasetResponse } from "@/types";
import { ScatterPlotDialog } from "./ScatterPlotDialog";

/**
 * The scatter plot dialog, bound to the app store and the active session.
 *
 * Mounted once in the layout so the attach menu and the chart panel open the
 * same dialog. Columns come from the dataset's stored profile, fetched when
 * the dialog opens so they reflect the dataset attached right now.
 */
export function ScatterPlotLauncher() {
  const open = useAppStore((s) => s.scatterDialogOpen);
  const close = useAppStore((s) => s.closeScatterDialog);
  const datasetId = useSessionStore(
    (s) => s.sessions.find((session) => session.id === s.activeSessionId)?.datasetId ?? null,
  );
  const { plot, plotting } = useScatterPlot();

  const [columns, setColumns] = useState<ScatterColumns | null>(null);
  const [fetchError, setFetchError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Start every opening from a blank slate (reset during render on the prop
  // change, React's documented pattern), then fetch the columns.
  const [wasOpen, setWasOpen] = useState(open);
  if (open !== wasOpen) {
    setWasOpen(open);
    setColumns(null);
    setFetchError(null);
    setError(null);
  }
  const loadError = open && !datasetId ? "Attach a dataset first." : fetchError;

  useEffect(() => {
    if (!open || !datasetId) return;
    let cancelled = false;
    api
      .get(`datasets/${datasetId}`)
      .json<DatasetResponse>()
      .then((dataset) => {
        if (!cancelled) setColumns(scatterColumns(dataset.profile_json));
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setFetchError(err instanceof Error ? err.message : "Couldn't load the columns");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [open, datasetId]);

  const handleSubmit = useCallback(
    async (request: ScatterRequest) => {
      setError(null);
      const outcome = await plot(request);
      if (outcome.ok) {
        close();
      } else {
        setError(outcome.error ?? "The plot could not be drawn.");
      }
    },
    [plot, close],
  );

  return (
    <ScatterPlotDialog
      open={open}
      onOpenChange={(next) => {
        if (!next) close();
      }}
      columns={columns}
      loadError={loadError}
      error={error}
      submitting={plotting}
      onSubmit={(request) => void handleSubmit(request)}
    />
  );
}
