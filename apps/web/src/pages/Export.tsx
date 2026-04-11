import { useState, useEffect, useRef, useCallback } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { FileText, Table2, FileJson, Loader2, FileSpreadsheet, Check } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import type { DatasetResponse } from "@/types";

type ExportFormat = "csv" | "xlsx" | "json" | "parquet";

interface FormatOption {
  id: ExportFormat;
  label: string;
  ext: string;
  icon: typeof FileText;
}

interface JobPollState {
  status: "pending" | "running" | "completed" | "failed";
  progress: number;
  message?: string;
}

const formats: FormatOption[] = [
  { id: "csv", label: "CSV", ext: ".csv", icon: FileText },
  { id: "xlsx", label: "Excel", ext: ".xlsx", icon: Table2 },
  { id: "json", label: "JSON", ext: ".json", icon: FileJson },
  { id: "parquet", label: "Parquet", ext: ".parquet", icon: FileSpreadsheet },
];

export default function Export() {
  const { datasetId } = useParams<{ datasetId: string }>();

  const datasetQuery = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api.get(`datasets/${datasetId}`).json<DatasetResponse>(),
    enabled: !!datasetId,
  });

  const dataset = datasetQuery.data ?? null;
  const datasetLoading = datasetQuery.isLoading;
  const datasetError = datasetQuery.isError
    ? (datasetQuery.error instanceof Error ? datasetQuery.error.message : "Failed to load dataset")
    : null;

  const [selectedFormat, setSelectedFormat] = useState<ExportFormat>("csv");
  const [generating, setGenerating] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [jobState, setJobState] = useState<JobPollState | null>(null);
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const pollingRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const stopPolling = useCallback(() => {
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
  }, []);

  useEffect(() => {
    if (!jobId) return;

    const poll = async () => {
      try {
        const data = await api.get(`jobs/${jobId}`)
          .json<{ status: JobPollState["status"]; progress: number; error_text?: string | null }>();

        setJobState({ status: data.status, progress: data.progress, message: data.error_text ?? undefined });

        if (data.status === "completed") {
          stopPolling();
          setGenerating(false);
          try {
            const dl = await api.get(`exports/${jobId}/download`).json<{ download_url: string }>();
            setDownloadUrl(dl.download_url);
          } catch {
            setError("Export completed but failed to get download URL.");
          }
        } else if (data.status === "failed") {
          stopPolling();
          setGenerating(false);
          setError(data.error_text ?? "Export failed.");
        }
      } catch {
        // retry
      }
    };

    void poll();
    pollingRef.current = setInterval(() => void poll(), 2000);
    return stopPolling;
  }, [jobId, stopPolling]);

  const handleGenerate = async () => {
    if (!datasetId) return;
    setGenerating(true);
    setError(null);
    setDownloadUrl(null);
    setJobState(null);
    setJobId(null);

    try {
      const data = await api
        .post(`exports/${datasetId}`, { json: { format: selectedFormat, columns: null } })
        .json<{ id: string; job_id?: string }>();
      setJobId(data.id ?? data.job_id ?? "");
    } catch (err) {
      setGenerating(false);
      setError(err instanceof Error ? err.message : "Failed to start export.");
    }
  };

  return (
    <div className="mx-auto max-w-3xl p-6 md:p-8">
      <h1 className="text-xl font-semibold text-ink">Export Data</h1>
      <p className="mt-0.5 text-[13px] text-ink-tertiary">Choose a format and download your dataset.</p>

      {datasetLoading && (
        <div className="mt-4 flex items-center gap-2 text-[13px] text-ink-muted">
          <Loader2 className="h-3.5 w-3.5 animate-spin" /> Loading...
        </div>
      )}

      {datasetError && (
        <div className="mt-4 rounded-md bg-coral-50 px-3 py-2 text-sm text-coral-700">{datasetError}</div>
      )}

      {dataset && (
        <div className="mt-4 rounded-lg border border-[var(--line)] bg-[var(--surface-primary)] px-4 py-3">
          <p className="text-sm font-medium text-ink">{dataset.filename}</p>
          <p className="mt-0.5 text-xs text-ink-muted">
            {dataset.row_count?.toLocaleString() ?? "—"} rows &middot; {dataset.col_count ?? "—"} columns
          </p>
        </div>
      )}

      {/* Format picker */}
      <div className="mt-6 grid grid-cols-4 gap-2">
        {formats.map((fmt) => {
          const active = selectedFormat === fmt.id;
          return (
            <button
              key={fmt.id}
              type="button"
              onClick={() => { setSelectedFormat(fmt.id); setDownloadUrl(null); }}
              className={cn(
                "flex flex-col items-center gap-2 rounded-lg border p-4 text-center transition-all",
                active
                  ? "border-brand-500 bg-brand-50"
                  : "border-[var(--line)] bg-[var(--surface-primary)] hover:border-[var(--line-strong)]",
              )}
            >
              <fmt.icon className={cn("h-6 w-6", active ? "text-brand-600" : "text-ink-muted")} />
              <div>
                <p className={cn("text-sm font-medium", active ? "text-brand-700" : "text-ink")}>{fmt.label}</p>
                <p className="text-[11px] text-ink-muted">{fmt.ext}</p>
              </div>
            </button>
          );
        })}
      </div>

      {error && (
        <div className="mt-4 rounded-md bg-coral-50 px-3 py-2 text-sm text-coral-700">{error}</div>
      )}

      {generating && jobState && (
        <div className="mt-5 space-y-1.5">
          <div className="flex items-center justify-between text-[13px] text-ink-tertiary">
            <span className="capitalize">{jobState.status}...</span>
            <span className="tabular-nums">{Math.round(jobState.progress)}%</span>
          </div>
          <div className="h-1.5 overflow-hidden rounded-full bg-[var(--surface-raised)]">
            <div className="h-full rounded-full bg-brand-500 transition-all" style={{ width: `${jobState.progress}%` }} />
          </div>
        </div>
      )}

      <div className="mt-6 flex gap-3">
        <Button
          size="sm"
          className="bg-brand-600 text-white hover:bg-brand-700"
          onClick={handleGenerate}
          disabled={generating || !datasetId}
        >
          {generating ? (
            <><Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> Generating...</>
          ) : (
            "Generate Export"
          )}
        </Button>

        {downloadUrl && (
          <Button variant="outline" size="sm" asChild>
            <a href={downloadUrl} target="_blank" rel="noopener noreferrer">
              <Check className="mr-1.5 h-3.5 w-3.5 text-teal-600" />
              Download {selectedFormat.toUpperCase()}
            </a>
          </Button>
        )}
      </div>
    </div>
  );
}
