import { Link, useNavigate } from "react-router-dom";
import {
  Upload,
  FileSpreadsheet,
  Sparkles,
  MessageSquare,
  Download,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DatasetResponse } from "@/types";

/* ── Helpers ─────────────────────────────────────────────────────────────── */

const statusStyle: Record<DatasetResponse["status"], string> = {
  uploaded: "bg-[var(--surface-raised)] text-ink-tertiary",
  profiling: "bg-brand-50 text-brand-600",
  ready: "bg-gold-50 text-gold-700 dark:bg-gold-50 dark:text-gold-600",
  error: "bg-coral-50 text-coral-700",
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
  });
}

function formatSize(bytes: number | null) {
  if (bytes == null) return "";
  if (bytes < 1024) return `${String(bytes)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

/* ── Skeleton ────────────────────────────────────────────────────────────── */

function DashboardSkeleton() {
  return (
    <div className="mt-6 space-y-2">
      {Array.from({ length: 3 }).map((_, i) => (
        <div
          key={i}
          className="flex items-center gap-4 rounded-lg border border-[var(--line)] bg-[var(--surface-primary)] p-4"
        >
          <Skeleton className="h-9 w-9 rounded-lg" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-1/3" />
            <Skeleton className="h-3 w-1/2" />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export default function Dashboard() {
  const navigate = useNavigate();
  const {
    data: datasets,
    isLoading,
    isError,
  } = useQuery<DatasetResponse[]>({
    queryKey: ["datasets"],
    queryFn: () => api.get("datasets/").json<DatasetResponse[]>(),
  });

  return (
    <div className="mx-auto max-w-4xl p-6 md:p-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-ink">Datasets</h1>
          <p className="mt-0.5 text-[13px] text-ink-tertiary">
            Upload, clean, analyze, and export your data.
          </p>
        </div>
        <Link to="/app/upload">
          <Button size="sm" className="bg-brand-600 text-white hover:bg-brand-700">
            <Upload className="mr-1.5 h-3.5 w-3.5" />
            Upload
          </Button>
        </Link>
      </div>

      {isLoading ? (
        <DashboardSkeleton />
      ) : isError ? (
        <div className="mt-16 text-center">
          <p className="text-sm text-coral-600">Failed to load datasets.</p>
        </div>
      ) : !datasets || datasets.length === 0 ? (
        <div className="mt-20 flex flex-col items-center text-center">
          <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-xl bg-brand-50">
            <FileSpreadsheet className="h-7 w-7 text-brand-500" />
          </div>
          <h2 className="text-lg font-semibold text-ink">No datasets yet</h2>
          <p className="mt-1.5 max-w-sm text-[13px] text-ink-tertiary">
            Upload your first spreadsheet and let DataPilot clean, analyze, and
            export your data.
          </p>
          <Link to="/app/upload" className="mt-5">
            <Button size="sm" className="bg-brand-600 text-white hover:bg-brand-700">
              <Upload className="mr-1.5 h-3.5 w-3.5" />
              Upload your first dataset
            </Button>
          </Link>
        </div>
      ) : (
        <div className="mt-6 space-y-2">
          {datasets.map((ds, idx) => (
            <Link
              key={ds.id}
              to={ds.status === "ready" ? `/app/clean/${ds.id}` : "#"}
              className="group flex items-center gap-3 rounded-lg border border-[var(--line)] bg-[var(--surface-primary)] p-4 transition-all duration-200 hover:border-[var(--line-strong)] hover:shadow-sm animate-fade-in-up md:gap-4"
              style={{ animationDelay: `${idx * 50}ms`, animationFillMode: "both" }}
            >
              {/* Icon */}
              <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-brand-50">
                <FileSpreadsheet className="h-4.5 w-4.5 text-brand-500" />
              </div>

              {/* Info */}
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <p className="truncate text-sm font-medium text-ink">
                    {ds.filename}
                  </p>
                  <Badge
                    variant="secondary"
                    className={cn("shrink-0 text-[11px] font-medium", statusStyle[ds.status])}
                  >
                    {ds.status}
                  </Badge>
                </div>
                <p className="mt-0.5 truncate text-xs text-ink-muted">
                  {ds.row_count != null
                    ? ds.row_count.toLocaleString()
                    : "—"}{" "}
                  rows &middot;{" "}
                  {ds.col_count != null ? ds.col_count : "—"} cols
                  {ds.file_size_bytes != null && (
                    <> &middot; {formatSize(ds.file_size_bytes)}</>
                  )}
                  {" "}&middot; {formatDate(ds.created_at)}
                </p>
              </div>

              {/* Actions — hidden on mobile, revealed on hover on desktop */}
              {ds.status === "ready" && (
                <div className="hidden shrink-0 items-center gap-0.5 opacity-0 transition-opacity group-hover:opacity-100 md:flex">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 px-2 text-xs text-ink-secondary hover:text-brand-600"
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/app/clean/${ds.id}`); }}
                  >
                    <Sparkles className="h-3.5 w-3.5" />
                    Clean
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 px-2 text-xs text-ink-secondary hover:text-brand-600"
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/app/analyze/${ds.id}`); }}
                  >
                    <MessageSquare className="h-3.5 w-3.5" />
                    Analyze
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 gap-1 px-2 text-xs text-ink-secondary hover:text-brand-600"
                    onClick={(e) => { e.preventDefault(); e.stopPropagation(); navigate(`/app/export/${ds.id}`); }}
                  >
                    <Download className="h-3.5 w-3.5" />
                    Export
                  </Button>
                </div>
              )}
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
