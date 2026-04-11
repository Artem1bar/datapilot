import { useState, useEffect } from "react";
import { Download, Trash2, Loader2, Database } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api } from "@/lib/api";
import type { DatasetResponse } from "@/types";

export default function CleanedDatasets() {
  const [datasets, setDatasets] = useState<DatasetResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    (async () => {
      try {
        const all = await api.get("datasets/").json<DatasetResponse[]>();
        setDatasets(all.filter((d) => d.status === "ready"));
      } catch (err) {
        setError(err instanceof Error ? err.message : "Failed to load datasets");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-ink-muted" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex h-full items-center justify-center">
        <p className="text-[13px] text-coral-600">{error}</p>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
      <div className="mb-6">
        <h1 className="text-xl font-semibold text-ink">Cleaned Datasets</h1>
        <p className="mt-1 text-[13px] text-ink-tertiary">
          Datasets that have been processed by Data Tiger.
        </p>
      </div>

      {datasets.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-center">
          <Database className="h-12 w-12 text-ink-muted/20" />
          <p className="mt-4 text-[13px] text-ink-muted">
            No cleaned datasets yet. Start a cleaning session to see results here.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {datasets.map((ds) => (
            <div
              key={ds.id}
              className="flex items-center gap-4 rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] p-4 transition-all duration-150 hover:shadow-sm"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <Database className="h-5 w-5" />
              </div>

              <div className="min-w-0 flex-1">
                <p className="truncate text-[13px] font-medium text-ink">
                  {ds.filename}
                </p>
                <p className="mt-0.5 text-[12px] text-ink-muted">
                  {ds.row_count} rows · {ds.col_count} cols · {formatSize(ds.file_size_bytes)}
                </p>
              </div>

              <Badge
                variant="outline"
                className="border-teal-200 bg-teal-50 text-teal-700 text-[11px]"
              >
                {ds.status}
              </Badge>

              <div className="flex gap-1">
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-ink-muted hover:text-brand-600"
                  onClick={() => window.open(`/api/v1/datasets/${ds.id}/download`, "_blank")}
                  title="Download"
                >
                  <Download className="h-4 w-4" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8 text-ink-muted hover:text-coral-600"
                  title="Delete"
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function formatSize(bytes: number | null): string {
  if (bytes == null) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
