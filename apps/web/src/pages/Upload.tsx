import { useState, useCallback, useEffect } from "react";
import { useNavigate } from "react-router-dom";
import { useDropzone } from "react-dropzone";
import { useQueryClient } from "@tanstack/react-query";
import {
  FileSpreadsheet,
  Upload as UploadIcon,
  AlertTriangle,
  Loader2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Progress } from "@/components/ui/progress";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useUpload } from "@/hooks/use-upload";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DatasetResponse, JobResponse } from "@/types";

/* ── Types ────────────────────────────────────────────────────────────────── */

interface ProfileColumnStats {
  dtype: string;
  null_count: number;
  null_pct: number;
  unique_count: number;
  mean?: number | null;
  min?: string | number | null;
  max?: string | number | null;
}

interface ProfileJson {
  columns: Record<string, ProfileColumnStats>;
  row_count?: number;
  col_count?: number;
}

interface ProfileColumn extends ProfileColumnStats {
  name: string;
}

const ACCEPTED = {
  "text/csv": [".csv"],
  "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
  "application/vnd.ms-excel": [".xls"],
};

type Stage = "drop" | "uploading" | "analyzing" | "preview";

/* ── Page ─────────────────────────────────────────────────────────────────── */

export default function Upload() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState<Stage>("drop");
  const [fileError, setFileError] = useState<string | null>(null);
  const [datasetId, setDatasetId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [dataset, setDataset] = useState<DatasetResponse | null>(null);
  const [jobError, setJobError] = useState<string | null>(null);

  const { upload, uploading, progress } = useUpload({
    onSuccess: (dsId, jId) => {
      setDatasetId(dsId);
      setJobId(jId);
      setStage("analyzing");
    },
    onError: (err) => {
      setFileError(err.message);
      setStage("drop");
    },
  });

  useEffect(() => {
    if (stage !== "analyzing" || !jobId) return;

    const interval = setInterval(async () => {
      try {
        const job = await api.get(`jobs/${jobId}`).json<JobResponse>();
        if (job.status === "completed") {
          clearInterval(interval);
          const ds = await api.get(`datasets/${datasetId}`).json<DatasetResponse>();
          setDataset(ds);
          queryClient.invalidateQueries({ queryKey: ["datasets"] });
          setStage("preview");
        } else if (job.status === "failed") {
          clearInterval(interval);
          setJobError(job.error_text ?? "Profiling failed");
          setStage("drop");
        }
      } catch {
        // transient — keep polling
      }
    }, 2000);

    return () => clearInterval(interval);
  }, [stage, jobId, datasetId, queryClient]);

  const onDrop = useCallback(
    (accepted: File[], rejected: { file: File }[]) => {
      setFileError(null);
      if (rejected.length > 0) {
        setFileError("Unsupported file type. Please use .csv, .xlsx, or .xls.");
        return;
      }
      if (accepted.length > 0) setFile(accepted[0]);
    },
    [],
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: ACCEPTED,
    multiple: false,
  });

  const handleUpload = async () => {
    if (!file) return;
    setStage("uploading");
    await upload(file);
  };

  const handleSampleData = async () => {
    setFileError(null);
    try {
      const resp = await fetch("/sample_survey.csv");
      const blob = await resp.blob();
      const sampleFile = new File([blob], "sample_survey.csv", { type: "text/csv" });
      setFile(sampleFile);
      setStage("uploading");
      await upload(sampleFile);
    } catch {
      setFileError("Failed to load sample data.");
    }
  };

  const handleReset = () => {
    setFile(null);
    setStage("drop");
    setFileError(null);
    setJobError(null);
    setDatasetId(null);
    setJobId(null);
    setDataset(null);
  };

  const formatSize = (bytes: number) => {
    if (bytes < 1024) return `${String(bytes)} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  };

  const profile = dataset?.profile_json as ProfileJson | null;
  const profileColumns: ProfileColumn[] = profile?.columns
    ? Object.entries(profile.columns).map(([name, stats]) => ({ name, ...stats }))
    : [];

  return (
    <div className="mx-auto max-w-3xl p-6 md:p-8">
      <h1 className="text-xl font-semibold text-ink">Upload a dataset</h1>
      <p className="mt-0.5 text-[13px] text-ink-tertiary">
        Drag and drop your spreadsheet or click to browse.
      </p>

      {/* ── Drop zone ──────────────────────────────────────────────────── */}
      {stage === "drop" && (
        <>
          <div
            {...getRootProps()}
            className={cn(
              "mt-6 flex cursor-pointer flex-col items-center justify-center rounded-lg border-2 border-dashed p-12 text-center transition-colors",
              isDragActive
                ? "border-brand-400 bg-brand-50"
                : "border-[var(--line-strong)] bg-[var(--surface-primary)] hover:border-brand-300",
              fileError && "border-coral-400",
            )}
          >
            <input {...getInputProps()} />
            {file ? (
              <div className="flex flex-col items-center gap-2">
                <FileSpreadsheet className="h-10 w-10 text-brand-500" />
                <p className="text-sm font-medium text-ink">{file.name}</p>
                <p className="text-xs text-ink-muted">{formatSize(file.size)}</p>
              </div>
            ) : (
              <div className="flex flex-col items-center gap-2">
                <UploadIcon className="h-10 w-10 text-ink-muted" />
                <p className="text-sm font-medium text-ink-secondary">
                  {isDragActive ? "Drop your file here" : "Drag & drop or click to browse"}
                </p>
                <p className="text-xs text-ink-muted">
                  Supports .csv, .xlsx, .xls
                </p>
              </div>
            )}
          </div>

          {(fileError || jobError) && (
            <div className="mt-3 flex items-center gap-2 text-sm text-coral-600">
              <AlertTriangle className="h-4 w-4" />
              {fileError ?? jobError}
            </div>
          )}

          <div className="mt-4 flex gap-3">
            <Button
              disabled={!file}
              onClick={handleUpload}
              size="sm"
              className="bg-brand-600 text-white hover:bg-brand-700"
            >
              <UploadIcon className="mr-1.5 h-3.5 w-3.5" />
              Upload
            </Button>
            <Button variant="outline" size="sm" onClick={handleSampleData}>
              Try sample data
            </Button>
          </div>
        </>
      )}

      {/* ── Uploading ──────────────────────────────────────────────────── */}
      {stage === "uploading" && (
        <div className="mt-8 space-y-4">
          <div className="flex items-center gap-3">
            <FileSpreadsheet className="h-5 w-5 text-brand-500" />
            <div className="flex-1">
              <p className="text-sm font-medium text-ink">{file?.name}</p>
              <Progress value={uploading ? progress : 100} className="mt-2 h-1.5" />
            </div>
            <span className="text-xs tabular-nums text-ink-muted">{progress}%</span>
          </div>
        </div>
      )}

      {/* ── Analyzing ──────────────────────────────────────────────────── */}
      {stage === "analyzing" && (
        <div className="mt-8 space-y-4">
          <div className="flex items-center gap-3">
            <Loader2 className="h-4 w-4 animate-spin text-brand-500" />
            <span className="text-sm font-medium text-ink">Analyzing your file...</span>
          </div>
          <div className="space-y-3">
            <Skeleton className="h-4 w-full" />
            <Skeleton className="h-4 w-5/6" />
            <Skeleton className="h-4 w-4/6" />
            <Skeleton className="h-28 w-full rounded-lg" />
          </div>
        </div>
      )}

      {/* ── Preview ────────────────────────────────────────────────────── */}
      {stage === "preview" && dataset && (
        <div className="mt-6 space-y-5">
          <div className="flex flex-wrap items-center gap-2 text-[13px] text-ink-tertiary">
            <Badge className="bg-teal-50 text-teal-700 text-[11px] font-medium">
              {dataset.status}
            </Badge>
            <span>{dataset.row_count?.toLocaleString() ?? "—"} rows</span>
            <span className="text-ink-muted">&middot;</span>
            <span>{dataset.col_count ?? "—"} columns</span>
            {dataset.file_size_bytes != null && (
              <>
                <span className="text-ink-muted">&middot;</span>
                <span>{formatSize(dataset.file_size_bytes)}</span>
              </>
            )}
          </div>

          {profileColumns.length > 0 && (
            <div className="overflow-x-auto rounded-lg border border-[var(--line)]">
              <Table>
                <TableHeader>
                  <TableRow className="bg-[var(--surface-raised)]">
                    <TableHead className="font-mono text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Column</TableHead>
                    <TableHead className="font-mono text-[11px] font-semibold uppercase tracking-wide text-ink-muted">Type</TableHead>
                    <TableHead className="font-mono text-[11px] font-semibold uppercase tracking-wide text-ink-muted text-right">Nulls</TableHead>
                    <TableHead className="font-mono text-[11px] font-semibold uppercase tracking-wide text-ink-muted text-right">Unique</TableHead>
                    <TableHead className="font-mono text-[11px] font-semibold uppercase tracking-wide text-ink-muted text-right">Min</TableHead>
                    <TableHead className="font-mono text-[11px] font-semibold uppercase tracking-wide text-ink-muted text-right">Max</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {profileColumns.map((col) => (
                    <TableRow key={col.name} className="hover:bg-[var(--surface-raised)]">
                      <TableCell className="font-mono text-[13px] font-medium text-ink">{col.name}</TableCell>
                      <TableCell className="font-mono text-[13px] text-ink-tertiary">{col.dtype}</TableCell>
                      <TableCell className={cn("font-mono text-[13px] text-right", col.null_count > 0 ? "text-amber-600" : "text-ink-muted")}>
                        {col.null_count.toLocaleString()}
                      </TableCell>
                      <TableCell className="font-mono text-[13px] text-right text-ink-muted">{col.unique_count.toLocaleString()}</TableCell>
                      <TableCell className="font-mono text-[13px] text-right text-ink-muted">{col.min != null ? String(col.min) : "—"}</TableCell>
                      <TableCell className="font-mono text-[13px] text-right text-ink-muted">{col.max != null ? String(col.max) : "—"}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}

          {profileColumns.some((c) => c.null_count > 0) && (
            <Badge className="bg-amber-50 text-amber-700 text-[11px] font-medium">
              <AlertTriangle className="mr-1 h-3 w-3" />
              {profileColumns.reduce((sum, c) => sum + c.null_count, 0).toLocaleString()}{" "}
              null values across {profileColumns.filter((c) => c.null_count > 0).length} columns
            </Badge>
          )}

          <div className="flex gap-3">
            <Button
              size="sm"
              className="bg-brand-600 text-white hover:bg-brand-700"
              onClick={() => navigate(`/app/clean/${datasetId}`)}
            >
              Clean this data
            </Button>
            <Button variant="outline" size="sm" onClick={handleReset}>
              Upload another
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
