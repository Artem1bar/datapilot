import { useState, useEffect, useCallback } from "react";
import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useMutation } from "@tanstack/react-query";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Button } from "@/components/ui/button";
import { Loader2, AlertCircle, CheckCircle2, Sparkles, Download, BarChart2, RefreshCw } from "lucide-react";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import type { DatasetResponse, JobResponse, CleaningStep } from "@/types";

/* ── Helpers ──────────────────────────────────────────────────────────────── */

interface StepWithToggle extends CleaningStep {
  accepted: boolean;
  confidence?: number;
}

const operationColors: Record<string, string> = {
  fill_null: "bg-teal-50 text-teal-700",
  cast_type: "bg-brand-50 text-brand-600",
  drop_null: "bg-coral-50 text-coral-700",
  deduplicate: "bg-amber-50 text-amber-700",
  rename_column: "bg-brand-50 text-brand-600",
  strip_whitespace: "bg-[var(--surface-raised)] text-ink-secondary",
  standardize_values: "bg-brand-50 text-brand-600",
  remove_outliers: "bg-coral-50 text-coral-700",
};

function useJobPoller(jobId: string | null, onComplete: (job: JobResponse) => void) {
  const [progress, setProgress] = useState(0);

  useEffect(() => {
    if (!jobId) return;

    const interval = setInterval(async () => {
      try {
        const job = await api.get(`jobs/${jobId}`).json<JobResponse>();
        setProgress(job.progress ?? 0);
        if (job.status === "completed" || job.status === "failed") {
          clearInterval(interval);
          onComplete(job);
        }
      } catch {
        clearInterval(interval);
      }
    }, 1500);

    return () => clearInterval(interval);
  }, [jobId, onComplete]);

  return progress;
}

/* ── Page ─────────────────────────────────────────────────────────────────── */

export default function Clean() {
  const { datasetId } = useParams<{ datasetId: string }>();
  const navigate = useNavigate();

  const [steps, setSteps] = useState<StepWithToggle[]>([]);
  const [planSummary, setPlanSummary] = useState<string>("");
  const [applyJobId, setApplyJobId] = useState<string | null>(null);
  const [applyStatus, setApplyStatus] = useState<"idle" | "polling" | "success" | "error">("idle");
  const [applyError, setApplyError] = useState<string>("");
  const [downloadUrl, setDownloadUrl] = useState<string | null>(null);
  const [userInstructions, setUserInstructions] = useState<string>("");

  const loadStepsFromJob = useCallback((job: JobResponse, append = false) => {
    const result = job.result_json as { steps?: (CleaningStep & { confidence?: number })[]; summary?: string } | null;
    if (result?.steps) {
      const newSteps = result.steps.map((s) => ({ ...s, accepted: true }));
      if (append) {
        setSteps((prev) => [...prev, ...newSteps]);
      } else {
        setSteps(newSteps);
      }
    }
    if (result?.summary && !append) setPlanSummary(result.summary);
  }, []);

  const datasetQuery = useQuery({
    queryKey: ["dataset", datasetId],
    queryFn: () => api.get(`datasets/${datasetId}`).json<DatasetResponse>(),
    enabled: !!datasetId,
  });

  const existingPlanQuery = useQuery({
    queryKey: ["cleaning-plan", datasetId],
    queryFn: async () => {
      try {
        return await api.get(`cleaning/${datasetId}/plan`).json<JobResponse>();
      } catch (err: unknown) {
        const error = err as { response?: { status?: number } };
        if (error?.response?.status === 404) return null;
        throw err;
      }
    },
    enabled: !!datasetId && datasetQuery.data?.status === "ready",
  });

  const generatePlanMutation = useMutation({
    mutationFn: (instructions?: string) =>
      api.post(`cleaning/${datasetId}/plan`, {
        timeout: 120_000,
        json: instructions ? { user_instructions: instructions } : undefined,
      }).json<JobResponse>(),
  });

  const [generateJobId, setGenerateJobId] = useState<string | null>(null);
  // separate job ID for "add instructions" flow so poller knows to append
  const [appendJobId, setAppendJobId] = useState<string | null>(null);

  useEffect(() => {
    if (
      existingPlanQuery.isSuccess &&
      existingPlanQuery.data === null &&
      !generatePlanMutation.isPending &&
      !generatePlanMutation.isSuccess &&
      !generateJobId
    ) {
      generatePlanMutation.mutate(undefined, {
        onSuccess: (job) => {
          if (job.status === "completed") {
            loadStepsFromJob(job);
          } else {
            setGenerateJobId(job.id);
          }
        },
      });
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- intentionally triggers only when query status/data change; adding mutation refs would cause loops
  }, [existingPlanQuery.isSuccess, existingPlanQuery.data, loadStepsFromJob]);

  useEffect(() => {
    if (existingPlanQuery.data && existingPlanQuery.data.status === "completed") {
      loadStepsFromJob(existingPlanQuery.data);
    } else if (existingPlanQuery.data && existingPlanQuery.data.status !== "completed") {
      setGenerateJobId(existingPlanQuery.data.id);
    }
  }, [existingPlanQuery.data, loadStepsFromJob]);

  const handleGenerateComplete = useCallback((job: JobResponse) => {
    if (job.status === "completed") loadStepsFromJob(job);
    setGenerateJobId(null);
  }, [loadStepsFromJob]);

  const handleAppendComplete = useCallback((job: JobResponse) => {
    if (job.status === "completed") loadStepsFromJob(job, true);
    setAppendJobId(null);
  }, [loadStepsFromJob]);

  useJobPoller(generateJobId, handleGenerateComplete);
  useJobPoller(appendJobId, handleAppendComplete);

  const applyMutation = useMutation({
    mutationFn: (selectedSteps: CleaningStep[]) =>
      api.post(`cleaning/${datasetId}/apply`, { json: { steps: selectedSteps } }).json<JobResponse>(),
    onSuccess: (job) => {
      setApplyJobId(job.id);
      setApplyStatus("polling");
    },
    onError: () => {
      setApplyStatus("error");
      setApplyError("Failed to start cleaning.");
    },
  });

  const handleApplyComplete = useCallback(
    async (job: JobResponse) => {
      if (job.status === "completed") {
        setApplyStatus("success");
        try {
          const dl = await api.get(`cleaning/${job.id}/download`).json<{ download_url: string }>();
          setDownloadUrl(dl.download_url);
        } catch {
          // Download URL is nice-to-have; don't block the success state
        }
      } else {
        setApplyStatus("error");
        setApplyError(job.error_text || "Cleaning failed.");
      }
    },
    [],
  );

  const applyProgress = useJobPoller(applyJobId, handleApplyComplete);

  const toggleStep = (index: number) => {
    setSteps((prev) => prev.map((s, i) => (i === index ? { ...s, accepted: !s.accepted } : s)));
  };

  const acceptedSteps = steps.filter((s) => s.accepted);
  const acceptedCount = acceptedSteps.length;

  const handleApply = () => {
    if (acceptedCount === 0) return;
    const toSend = acceptedSteps.map(({ accepted: _accepted, confidence: _confidence, ...rest }) => rest);
    applyMutation.mutate(toSend);
  };

  const isGenerating = (generatePlanMutation.isPending || !!generateJobId || existingPlanQuery.isLoading) && steps.length === 0;
  const isAppending = (generatePlanMutation.isPending || !!appendJobId) && steps.length > 0;

  if (datasetQuery.isLoading) {
    return (
      <div className="flex h-full items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
      </div>
    );
  }

  if (datasetQuery.isError) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <AlertCircle className="h-8 w-8 text-coral-600" />
        <p className="text-sm text-ink-tertiary">Failed to load dataset.</p>
      </div>
    );
  }

  if (datasetQuery.data && datasetQuery.data.status !== "ready") {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3">
        <Loader2 className="h-6 w-6 animate-spin text-brand-500" />
        <p className="text-sm text-ink-tertiary">
          Dataset is still processing. Status: {datasetQuery.data.status}
        </p>
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col lg:flex-row">
      {/* ── Left: Cleaning steps ───────────────────────────────────────── */}
      <div className="w-full shrink-0 overflow-y-auto border-b border-[var(--line)] p-6 lg:w-[420px] lg:border-b-0 lg:border-r">
        <h2 className="text-lg font-semibold text-ink">Cleaning Plan</h2>
        <p className="mt-0.5 text-[13px] text-ink-tertiary">
          Review and toggle each suggested change.
        </p>

        {isGenerating ? (
          <div className="mt-16 flex flex-col items-center gap-3 text-center">
            <div className="relative">
              <Loader2 className="h-8 w-8 animate-spin text-brand-500" />
              <Sparkles className="absolute -right-1 -top-1 h-3.5 w-3.5 text-amber-500" />
            </div>
            <p className="text-sm font-medium text-ink-secondary">Generating cleaning plan...</p>
            <p className="text-xs text-ink-muted">AI is analyzing your dataset</p>
          </div>
        ) : steps.length === 0 ? (
          <div className="mt-16 flex flex-col items-center gap-3 text-center">
            <CheckCircle2 className="h-8 w-8 text-teal-600" />
            <p className="text-sm text-ink-tertiary">No cleaning steps needed. Your data looks great!</p>
          </div>
        ) : (
          <div className="mt-4 space-y-2">
            {planSummary && (
              <p className="mb-3 rounded-lg bg-brand-50 p-3 text-[13px] text-brand-700 animate-fade-in">
                {planSummary}
              </p>
            )}
            {steps.map((step, index) => (
              <div
                key={index}
                className={cn(
                  "rounded-lg border bg-[var(--surface-primary)] p-3.5 transition-all duration-200 animate-fade-in-up",
                  step.accepted
                    ? "border-brand-500/20 shadow-sm"
                    : "border-[var(--line)] opacity-60",
                )}
                style={{ animationDelay: `${index * 60}ms`, animationFillMode: "both" }}
              >
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 space-y-1.5">
                    <div className="flex items-center gap-2">
                      <Badge
                        variant="secondary"
                        className={cn("text-[11px] font-medium", operationColors[step.operation] ?? "bg-[var(--surface-raised)] text-ink-secondary")}
                      >
                        {step.operation}
                      </Badge>
                      {step.column && (
                        <span className="font-mono text-[11px] text-ink-muted">{step.column}</span>
                      )}
                    </div>
                    <p className="text-[13px] leading-relaxed text-ink-secondary">{step.description}</p>
                    {step.confidence != null && (
                      <div className="flex items-center gap-2">
                        <Progress value={step.confidence} className="h-1 flex-1" />
                        <span className="text-[11px] tabular-nums text-ink-muted">{step.confidence}%</span>
                      </div>
                    )}
                  </div>
                  <Switch
                    checked={step.accepted}
                    onCheckedChange={() => toggleStep(index)}
                    disabled={applyStatus === "polling"}
                  />
                </div>
              </div>
            ))}
          </div>
        )}

        {/* ── Appending indicator ─────────────────────────────────── */}
        {isAppending && (
          <div className="mt-3 flex items-center gap-2 text-[13px] text-ink-muted">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-brand-500" />
            Adding steps from instructions...
          </div>
        )}

        {/* ── Custom instructions ──────────────────────────────────── */}
        {!isGenerating && applyStatus === "idle" && (
          <div className="mt-5 space-y-2 border-t border-[var(--line)] pt-4">
            <label className="text-[13px] font-medium text-ink-secondary">
              Additional cleaning instructions
            </label>
            <Textarea
              placeholder="Tell the AI about other data you need cleaned, e.g. 'Remove all rows where ResponseId is empty' or 'Convert all date columns to MM/DD/YYYY format'..."
              value={userInstructions}
              onChange={(e) => setUserInstructions(e.target.value)}
              className="min-h-[72px] resize-y text-[13px]"
              maxLength={2000}
            />
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              disabled={generatePlanMutation.isPending || !userInstructions.trim()}
              onClick={() => {
                const isAppend = steps.length > 0;
                generatePlanMutation.mutate(userInstructions, {
                  onSuccess: (job) => {
                    if (job.status === "completed") {
                      loadStepsFromJob(job, isAppend);
                    } else if (isAppend) {
                      setAppendJobId(job.id);
                    } else {
                      setGenerateJobId(job.id);
                    }
                    setUserInstructions("");
                  },
                });
              }}
            >
              <RefreshCw className="mr-1.5 h-3.5 w-3.5" />
              {steps.length > 0 ? "Add Steps" : "Generate Plan"}
            </Button>
          </div>
        )}
      </div>

      {/* ── Right: Status panel ────────────────────────────────────────── */}
      <div className="flex flex-1 flex-col overflow-hidden">
        <div className="flex flex-1 flex-col items-center justify-center p-6 text-center">
          {applyStatus === "polling" && (
            <div className="space-y-3">
              <Loader2 className="mx-auto h-8 w-8 animate-spin text-brand-500" />
              <p className="text-sm font-medium text-ink-secondary">Applying cleaning steps...</p>
              <Progress value={applyProgress} className="mx-auto h-1.5 w-48" />
              <p className="text-xs text-ink-muted">{applyProgress}% complete</p>
            </div>
          )}

          {applyStatus === "success" && (
            <div className="flex flex-col items-center gap-4 animate-scale-in">
              <CheckCircle2 className="h-10 w-10 text-teal-600" />
              <div className="space-y-1 text-center">
                <p className="text-sm font-medium text-ink">Cleaning complete!</p>
                <p className="text-xs text-ink-muted">
                  The cleaned file includes a Cleaning Legend sheet with all changes.
                </p>
              </div>
              <div className="flex flex-col gap-2 w-full max-w-xs">
                {downloadUrl && (
                  <Button size="sm" className="bg-teal-600 text-white hover:bg-teal-700 w-full" asChild>
                    <a href={downloadUrl} target="_blank" rel="noopener noreferrer">
                      <Download className="mr-1.5 h-3.5 w-3.5" />
                      Download Cleaned Excel
                    </a>
                  </Button>
                )}
                <Button
                  size="sm"
                  variant="outline"
                  className="w-full"
                  onClick={() => navigate(`/app/analyze/${datasetId}`)}
                >
                  <BarChart2 className="mr-1.5 h-3.5 w-3.5" />
                  Go to Analysis
                </Button>
              </div>
            </div>
          )}

          {applyStatus === "error" && (
            <div className="space-y-3">
              <AlertCircle className="mx-auto h-10 w-10 text-coral-600" />
              <p className="text-sm text-coral-600">{applyError}</p>
              <Button variant="outline" size="sm" onClick={() => setApplyStatus("idle")}>
                Try again
              </Button>
            </div>
          )}

          {applyStatus === "idle" && !isGenerating && steps.length > 0 && (
            <div className="space-y-3">
              <p className="text-sm text-ink-tertiary">
                <span className="font-semibold text-brand-600">{acceptedCount}</span> of{" "}
                <span className="font-semibold text-ink">{steps.length}</span> steps selected
              </p>
              <p className="text-xs text-ink-muted">
                Toggle steps on or off, then apply to clean your dataset.
              </p>
            </div>
          )}

          {applyStatus === "idle" && isGenerating && (
            <p className="text-sm text-ink-muted">Waiting for cleaning plan...</p>
          )}
        </div>

        {steps.length > 0 && (
          <div className="border-t border-[var(--line)] bg-[var(--surface-primary)] p-4">
            <Button
              className="w-full bg-brand-600 text-white hover:bg-brand-700 transition-all duration-150 hover:shadow-md active:scale-[0.98] disabled:opacity-40"
              size="sm"
              disabled={acceptedCount === 0 || applyStatus === "polling" || applyMutation.isPending}
              onClick={handleApply}
            >
              {applyMutation.isPending || applyStatus === "polling" ? (
                <>
                  <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" />
                  Applying...
                </>
              ) : (
                `Apply ${acceptedCount} change${acceptedCount !== 1 ? "s" : ""}`
              )}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
