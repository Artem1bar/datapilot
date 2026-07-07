import { useState, useCallback, useEffect, useMemo, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useSessionStore, createMessage } from "@/stores/session-store";
import { useAppStore } from "@/stores/app-store";
import { ChatStream } from "@/components/chat/ChatStream";
import { InputBar } from "@/components/chat/InputBar";
import { WorkflowStepper } from "@/components/workflow/WorkflowStepper";
import { api } from "@/lib/api";
import { detectIntent, intentRequiresData } from "@/lib/intent";
import { progressStageLabel } from "@/lib/progress";
import type {
  DatasetResponse,
  JobResponse,
  CleaningStep,
  ChartConfig,
  InspectionSummaryPayload,
  CleaningPlanPayload,
  CleaningProgressPayload,
  ValidationSummaryPayload,
  CleaningResultsPayload,
  ManipulationPreviewPayload,
  ManipulationResultPayload,
} from "@/types";

/* ── Helpers ────────────────────────────────────────────────────────────── */

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/* ── Component ──────────────────────────────────────────────────────────── */

export default function Chat() {
  const activeSessionId = useSessionStore((s) => s.activeSessionId);
  const EMPTY_MESSAGES: readonly import("@/types").ChatMessageV2[] = useMemo(() => [], []);
  const rawMessages = useSessionStore(
    (s) => (activeSessionId ? s.messagesBySession[activeSessionId] : undefined),
  );
  const messages = rawMessages ?? EMPTY_MESSAGES;
  const workflowState = useSessionStore((s) =>
    s.activeSessionId ? s.workflowStateBySession[s.activeSessionId] : undefined,
  );
  const addMessage = useSessionStore((s) => s.addMessage);
  const createSession = useSessionStore((s) => s.createSession);
  const setSessionDatasetId = useSessionStore((s) => s.setSessionDatasetId);
  const startWorkflow = useSessionStore((s) => s.startWorkflow);
  const setWorkflowStep = useSessionStore((s) => s.setWorkflowStep);
  const clearWorkflow = useSessionStore((s) => s.clearWorkflow);
  const renameSession = useSessionStore((s) => s.renameSession);

  const addCharts = useAppStore((s) => s.addCharts);
  const setChartPanelOpen = useAppStore((s) => s.setChartPanelOpen);
  const clearCharts = useAppStore((s) => s.clearCharts);

  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);

  // Ensure a session exists
  useEffect(() => {
    if (!activeSessionId) {
      createSession();
    }
  }, [activeSessionId, createSession]);

  // Clear charts only when the session *actually* changes (not on initial mount)
  const prevSessionRef = useRef(activeSessionId);
  useEffect(() => {
    if (prevSessionRef.current !== activeSessionId && prevSessionRef.current !== null) {
      clearCharts();
    }
    prevSessionRef.current = activeSessionId;
  }, [activeSessionId, clearCharts]);

  /* ── Upload handler ──────────────────────────────────────────────────── */

  const handleFileAttach = useCallback(
    async (file: File) => {
      let sessionId = activeSessionId;
      if (!sessionId) {
        sessionId = createSession(file.name);
      }

      setSending(true);
      addMessage(sessionId, createMessage("system", `Uploading **${file.name}**...`));

      try {
        // Upload file directly through the backend (avoids CORS with MinIO)
        const formData = new FormData();
        formData.append("file", file);

        const uploadResp = await api
          .post("datasets/upload", { body: formData })
          .json<{ dataset_id: string }>();

        const datasetId = uploadResp.dataset_id;
        setSessionDatasetId(sessionId, datasetId);
        renameSession(sessionId, file.name);

        // 4. Wait for profiling
        addMessage(sessionId, createMessage("system", "Profiling your dataset..."));
        const ready = await pollDatasetReady(datasetId);

        // 5. Show ready message — don't trigger cleaning, let user choose
        addMessage(
          sessionId,
          createMessage(
            "assistant",
            `**${ready.filename}** is ready — ${ready.row_count?.toLocaleString()} rows, ${ready.col_count} columns.\n\nWhat would you like to do with it?`,
          ),
        );
      } catch (err) {
        addMessage(
          sessionId,
          createMessage("system", `Upload failed: ${err instanceof Error ? err.message : "Unknown error"}`),
        );
      } finally {
        setSending(false);
      }
    },
    [activeSessionId, addMessage, createSession, setSessionDatasetId, renameSession],
  );

  /* ── Table paste handler ─────────────────────────────────────────────── */

  const handleTablePaste = useCallback(
    (text: string) => {
      // Detect delimiter: TSV (tab-separated from spreadsheet copy) or CSV
      const firstLine = text.split(/\r?\n/)[0] ?? "";
      const isTabSeparated = firstLine.includes("\t");

      let csvContent: string;
      if (isTabSeparated) {
        // Convert TSV → CSV: quote fields that contain commas or quotes
        csvContent = text
          .split(/\r?\n/)
          .map((row) =>
            row
              .split("\t")
              .map((cell) => {
                const needsQuote = cell.includes(",") || cell.includes('"') || cell.includes("\n");
                return needsQuote ? `"${cell.replaceAll('"', '""')}"` : cell;
              })
              .join(","),
          )
          .join("\n");
      } else {
        csvContent = text;
      }

      const filename = "pasted-table.csv";
      const blob = new Blob([csvContent], { type: "text/csv" });
      const file = new File([blob], filename, { type: "text/csv" });
      void handleFileAttach(file);
    },
    [handleFileAttach],
  );

  /* ── Send message / route intent ─────────────────────────────────────── */

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || sending) return;

    let sessionId = activeSessionId;
    if (!sessionId) {
      sessionId = createSession();
    }

    setInput("");
    addMessage(sessionId, createMessage("user", text));

    const sessions = useSessionStore.getState().sessions;
    const session = sessions.find((s) => s.id === sessionId);
    const datasetId = session?.datasetId;

    // Route by intent (classification + tests live in lib/intent.ts)
    const intent = detectIntent(text);
    const isCleanIntent = intent === "clean";
    const isAnalyzeIntent = intent === "analyze";
    const isManipulationIntent = intent === "manipulate";

    if (!datasetId && intentRequiresData(intent)) {
      addMessage(
        sessionId,
        createMessage("assistant", "I need some data to work with. Please attach a CSV or Excel file using the **+** button, then try again."),
      );
      return;
    }

    if (isCleanIntent && datasetId) {
      await runCleaningWorkflow(sessionId, datasetId);
      return;
    }

    if (isManipulationIntent && datasetId) {
      setSending(true);
      try {
        addMessage(sessionId, createMessage("system", "Parsing your edit command..."));

        const preview = await api
          .post(`manipulation/${datasetId}/parse`, {
            json: { command: text },
            timeout: 60_000,
          })
          .json<{
            operations: Array<{ op_type: string; params: Record<string, unknown>; description: string }>;
            preview_before: Record<string, unknown>[];
            preview_after: Record<string, unknown>[];
            affected_columns: string[];
            affected_row_count: number;
            warnings: string[];
            confirmation_required: boolean;
          }>();

        const previewCard: ManipulationPreviewPayload = {
          type: "manipulation_preview",
          command: text,
          operations: preview.operations.map(op => ({
            opType: op.op_type,
            params: op.params,
            description: op.description,
          })),
          previewBefore: preview.preview_before,
          previewAfter: preview.preview_after,
          affectedColumns: preview.affected_columns,
          affectedRowCount: preview.affected_row_count,
          warnings: preview.warnings,
          confirmationRequired: preview.confirmation_required,
        };
        addMessage(sessionId, createMessage("assistant", "", previewCard));
      } catch (err) {
        addMessage(sessionId, createMessage("system", `Edit failed: ${err instanceof Error ? err.message : "Unknown error"}`));
      } finally {
        setSending(false);
      }
      return;
    }

    if (isAnalyzeIntent && datasetId) {
      setSending(true);
      try {
        const resp = await api
          .post(`analysis/${datasetId}/chat`, {
            json: { message: text },
            timeout: 180_000,
          })
          .json<{ id: string; messages_json: Array<{ role: string; content: string; charts?: ChartConfig[] }> }>();

        const lastMsg = resp.messages_json[resp.messages_json.length - 1];
        if (lastMsg && lastMsg.role === "assistant") {
          addMessage(sessionId, createMessage("assistant", lastMsg.content));
          if (lastMsg.charts && lastMsg.charts.length > 0) {
            addCharts(lastMsg.charts);
            setChartPanelOpen(true);
          }
        }
      } catch (err) {
        addMessage(
          sessionId,
          createMessage("system", `Analysis error: ${err instanceof Error ? err.message : "Unknown error"}`),
        );
      } finally {
        setSending(false);
      }
      return;
    }

    // Default: general chat / analysis
    if (datasetId) {
      setSending(true);
      try {
        const resp = await api
          .post(`analysis/${datasetId}/chat`, {
            json: { message: text },
            timeout: 180_000,
          })
          .json<{ id: string; messages_json: Array<{ role: string; content: string; charts?: ChartConfig[] }> }>();

        const lastMsg = resp.messages_json[resp.messages_json.length - 1];
        if (lastMsg && lastMsg.role === "assistant") {
          addMessage(sessionId, createMessage("assistant", lastMsg.content));
          if (lastMsg.charts && lastMsg.charts.length > 0) {
            addCharts(lastMsg.charts);
            setChartPanelOpen(true);
          }
        }
      } catch (err) {
        addMessage(
          sessionId,
          createMessage("system", `Error: ${err instanceof Error ? err.message : "Unknown error"}`),
        );
      } finally {
        setSending(false);
      }
    } else {
      addMessage(
        sessionId,
        createMessage("assistant", "Welcome! Upload a CSV or Excel file to get started. Click the **+** button or drag a file into the chat."),
      );
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps -- runCleaningWorkflow is a stable inner fn; addCharts/setChartPanelOpen are stable Zustand actions
  }, [input, sending, activeSessionId, addMessage, createSession, addCharts, setChartPanelOpen]);

  /* ── Cleaning workflow ───────────────────────────────────────────────── */

  async function runCleaningWorkflow(sessionId: string, datasetId: string) {
    setSending(true);

    try {
      // Fetch dataset info
      const dataset = await api.get(`datasets/${datasetId}/`).json<DatasetResponse>();
      startWorkflow(sessionId, datasetId, dataset.filename);

      // ── Step 1: Inspect ──────────────────────────────────────
      setWorkflowStep(sessionId, "inspect", "active");
      addMessage(sessionId, createMessage("system", "Inspecting your dataset..."));

      const profile = dataset.profile_json as Record<string, unknown> | null;
      const columns = profile?.columns as Record<string, Record<string, unknown>> | undefined;

      const inspectionCard: InspectionSummaryPayload = {
        type: "inspection_summary",
        filename: dataset.filename,
        rowCount: dataset.row_count ?? 0,
        colCount: dataset.col_count ?? 0,
        fileSizeBytes: dataset.file_size_bytes,
        columns: columns
          ? Object.entries(columns).map(([name, col]) => ({
              name,
              dtype: (col.dtype as string) ?? "unknown",
              nullPct: (col.null_pct as number) ?? 0,
              uniqueCount: (col.unique_count as number) ?? 0,
            }))
          : [],
      };

      addMessage(sessionId, createMessage("assistant", "", inspectionCard));
      setWorkflowStep(sessionId, "inspect", "complete");

      // ── Step 2: Plan ─────────────────────────────────────────
      setWorkflowStep(sessionId, "plan", "active");
      addMessage(sessionId, createMessage("system", "Generating cleaning plan..."));

      const planJob = await api
        .post(`cleaning/${datasetId}/plan`, { json: {}, timeout: 180_000 })
        .json<JobResponse>();

      // The plan endpoint returns a JobResponse — steps live inside result_json
      const planData = planJob.result_json as {
        steps: Array<CleaningStep & { confidence?: number; rationale?: string }>;
        summary: string;
      } | null;
      if (!planData?.steps?.length) {
        throw new Error("No cleaning steps were generated. Try again or check your dataset.");
      }

      const planCard: CleaningPlanPayload = {
        type: "cleaning_plan",
        summary: planData.summary ?? `AI-generated cleaning plan with ${planData.steps.length} steps`,
        datasetId,
        steps: planData.steps,
      };

      addMessage(sessionId, createMessage("assistant", "", planCard));
      setWorkflowStep(sessionId, "plan", "complete");
      // The workflow pauses here for user approval. The plan card lets the user
      // toggle steps and press "Apply", which dispatches the "apply_cleaning"
      // card action → applyCleaningSteps(). Nothing is applied automatically.
    } catch (err) {
      addMessage(
        sessionId,
        createMessage("system", `Cleaning error: ${err instanceof Error ? err.message : "Unknown error"}`),
      );
      clearWorkflow(sessionId);
    } finally {
      setSending(false);
    }
  }

  // Applies user-approved cleaning steps: runs the clean job, streams progress,
  // then shows the validation + results cards. Triggered by the plan card's
  // Apply button (the "apply_cleaning" card action) — never automatically.
  async function applyCleaningSteps(
    sessionId: string,
    datasetId: string,
    steps: CleaningStep[],
  ) {
    setSending(true);

    try {
      const dataset = await api.get(`datasets/${datasetId}/`).json<DatasetResponse>();

      // ── Step 3: Clean ────────────────────────────────────────
      setWorkflowStep(sessionId, "clean", "active");

      const progressMsgId = generateId();
      const progressCard: CleaningProgressPayload = {
        type: "cleaning_progress",
        progress: 0,
        status: "running",
        message: "Applying cleaning plan...",
      };
      addMessage(sessionId, {
        id: progressMsgId,
        role: "assistant",
        content: "",
        card: progressCard,
        timestamp: new Date().toISOString(),
      });

      const applyJob = await api
        .post(`cleaning/${datasetId}/apply`, {
          json: { steps },
          timeout: 180_000,
        })
        .json<JobResponse>();

      // Poll job — apply endpoint returns JobResponse with id, not job_id.
      // The worker persists per-stage progress on the Job row, so polling
      // drives an honest progress bar.
      const updateMessage = useSessionStore.getState().updateMessage;
      const jobResult = await pollJob(applyJob.id, (progress) => {
        updateMessage(sessionId, progressMsgId, {
          card: {
            type: "cleaning_progress",
            progress,
            status: "running",
            message: progressStageLabel(progress),
          },
        });
      });

      // Update progress card to complete
      updateMessage(sessionId, progressMsgId, {
        card: {
          type: "cleaning_progress",
          progress: 100,
          status: "complete",
          message: "Cleaning complete!",
        },
      });

      setWorkflowStep(sessionId, "clean", "complete");

      // ── Step 4: Validate ─────────────────────────────────────
      setWorkflowStep(sessionId, "validate", "active");
      addMessage(sessionId, createMessage("system", "Validating results..."));

      const result = jobResult.result_json as Record<string, unknown> | null;
      const verification = result?.verification as Record<string, unknown> | undefined;

      if (verification) {
        const stepResults = (verification.step_results as Array<Record<string, unknown>>) ?? [];
        const validationCard: ValidationSummaryPayload = {
          type: "validation_summary",
          results: stepResults.map((r, idx) => ({
            stepDescription: `Step ${((r.step_index as number) ?? idx) + 1}: [${r.operation ?? "unknown"}] ${r.column ? `on "${r.column}"` : "(all columns)"}`,
            passed: (r.passed as boolean) ?? false,
            detail: (r.actual as string) ?? null,
          })),
          overallPassed: (verification.overall_passed as boolean) ?? stepResults.every((r) => r.passed),
        };
        addMessage(sessionId, createMessage("assistant", "", validationCard));
      }

      setWorkflowStep(sessionId, "validate", "complete");

      // ── Final results card ───────────────────────────────────
      const rowsBefore = dataset.row_count ?? 0;
      // result_json fields: cleaned_rows, rows_removed, cells_modified
      const rowsAfter = (result?.cleaned_rows as number) ?? rowsBefore;
      const issuesResolved = (result?.cells_modified as number) ?? 0;
      const remediationApplied = !!(
        verification?.agent_assessment as Record<string, unknown> | undefined
      )?.remediation_applied;
      const unresolvableFlags = (verification?.unresolvable_flags as string[] | undefined) ?? [];

      const resultsCard: CleaningResultsPayload = {
        type: "cleaning_results",
        downloadUrl: `/api/v1/cleaning/${applyJob.id}/download`,
        rowsBefore,
        rowsAfter,
        issuesResolved,
        datasetId,
        remediationApplied,
        unresolvableFlags,
      };
      addMessage(sessionId, createMessage("assistant", "", resultsCard));

      clearWorkflow(sessionId);
    } catch (err) {
      addMessage(
        sessionId,
        createMessage("system", `Cleaning error: ${err instanceof Error ? err.message : "Unknown error"}`),
      );
      clearWorkflow(sessionId);
    } finally {
      setSending(false);
    }
  }

  /* ── Card actions ────────────────────────────────────────────────────── */

  const handleCardAction = useCallback(
    async (action: string, data?: unknown, ownerSessionId?: string) => {
      if (action === "download" && typeof data === "string") {
        // Use an anchor click so the browser triggers a proper file download
        // (the URL now streams the file directly — no JSON redirect needed)
        const a = document.createElement("a");
        a.href = data;
        a.download = "";
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
      }
      if (action === "analyze" && typeof data === "string") {
        const sessionId = ownerSessionId ?? activeSessionId;
        if (sessionId) {
          setInput("Analyze my data");
        }
      }

      if (action === "apply_cleaning" && data) {
        const sessionId = ownerSessionId ?? activeSessionId;
        if (!sessionId) return;
        const { datasetId, steps, messageId } = data as {
          datasetId?: string;
          steps?: CleaningStep[];
          messageId?: string;
        };
        if (!datasetId || !steps?.length) return;
        // Persist the applied state on the plan message so the card stays
        // "Applied" across remounts instead of becoming re-applyable.
        if (messageId) {
          const store = useSessionStore.getState();
          const msg = (store.messagesBySession[sessionId] ?? []).find((m) => m.id === messageId);
          if (msg?.card?.type === "cleaning_plan") {
            store.updateMessage(sessionId, messageId, { card: { ...msg.card, applied: true } });
          }
        }
        await applyCleaningSteps(sessionId, datasetId, steps);
      }

      if (action === "apply_manipulation" && data) {
        const sessionId = ownerSessionId ?? activeSessionId;
        if (!sessionId) return;
        const sessions = useSessionStore.getState().sessions;
        const session = sessions.find((s) => s.id === sessionId);
        const datasetId = session?.datasetId;
        if (!datasetId) return;

        setSending(true);
        addMessage(sessionId, createMessage("system", "Applying changes..."));
        try {
          const operations = (data as Array<{ opType: string; params: Record<string, unknown>; description: string }>).map(op => ({
            op_type: op.opType,
            params: op.params,
            description: op.description,
          }));
          const result = await api
            .post(`manipulation/${datasetId}/apply`, {
              json: { operations },
              timeout: 60_000,
            })
            .json<{
              success: boolean;
              snapshot_id: string;
              new_row_count: number;
              new_col_count: number;
              columns_added: string[];
              columns_removed: string[];
              columns_renamed: Record<string, string>;
              sample_rows: Record<string, unknown>[];
            }>();

          const resultCard: ManipulationResultPayload = {
            type: "manipulation_result",
            success: result.success,
            snapshotId: result.snapshot_id,
            newRowCount: result.new_row_count,
            newColCount: result.new_col_count,
            columnsAdded: result.columns_added,
            columnsRemoved: result.columns_removed,
            columnsRenamed: result.columns_renamed,
            sampleRows: result.sample_rows,
          };
          addMessage(sessionId, createMessage("assistant", "", resultCard));
        } catch (err) {
          addMessage(sessionId, createMessage("system", `Apply failed: ${err instanceof Error ? err.message : "Unknown error"}`));
        } finally {
          setSending(false);
        }
      }

      if (action === "cancel_manipulation") {
        const sessionId = ownerSessionId ?? activeSessionId;
        if (sessionId) {
          addMessage(sessionId, createMessage("system", "Edit cancelled."));
        }
      }

      if (action === "undo_manipulation" && typeof data === "string") {
        const sessionId = ownerSessionId ?? activeSessionId;
        if (!sessionId) return;
        const sessions = useSessionStore.getState().sessions;
        const session = sessions.find((s) => s.id === sessionId);
        const datasetId = session?.datasetId;
        if (!datasetId) return;

        setSending(true);
        addMessage(sessionId, createMessage("system", "Undoing changes..."));
        try {
          const result = await api
            .post(`manipulation/${datasetId}/undo`, {
              json: { snapshot_id: data },
              timeout: 30_000,
            })
            .json<{
              success: boolean;
              snapshot_id: string;
              new_row_count: number;
              new_col_count: number;
              sample_rows: Record<string, unknown>[];
            }>();

          addMessage(sessionId, createMessage("system", `Undo complete — restored to ${result.new_row_count} rows, ${result.new_col_count} columns.`));
        } catch (err) {
          addMessage(sessionId, createMessage("system", `Undo failed: ${err instanceof Error ? err.message : "Unknown error"}`));
        } finally {
          setSending(false);
        }
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps -- applyCleaningSteps is a stable inner fn (closes only over stable store actions/module fns), same pattern as runCleaningWorkflow above
    [activeSessionId, addMessage, setSending],
  );

  /* ── Chip click ──────────────────────────────────────────────────────── */

  const handleChipClick = useCallback(
    (text: string) => {
      setInput(text);
    },
    [],
  );

  /* ── Render ──────────────────────────────────────────────────────────── */

  return (
    <div className="flex h-full flex-col">
      {/* Workflow stepper (visible during cleaning) */}
      <AnimatePresence>
        {workflowState && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: "auto", opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ type: "spring", stiffness: 300, damping: 30 }}
            className="border-b border-[var(--line)] bg-[var(--surface-primary)] px-4 py-2 overflow-hidden"
          >
            <WorkflowStepper steps={workflowState.steps} filename={workflowState.datasetFilename} />
          </motion.div>
        )}
      </AnimatePresence>

      {/* Chat stream */}
      <ChatStream
        messages={messages}
        sessionId={activeSessionId}
        sending={sending}
        onChipClick={handleChipClick}
        onCardAction={handleCardAction}
      />

      {/* Input bar */}
      <InputBar
        value={input}
        onChange={setInput}
        onSend={() => void handleSend()}
        onFileAttach={(file) => void handleFileAttach(file)}
        onTablePaste={handleTablePaste}
        onChipClick={handleChipClick}
        sending={sending}
        showChips={messages.length === 0}
      />
    </div>
  );
}

/* ── Polling helpers ──────────────────────────────────────────────────── */

async function pollDatasetReady(datasetId: string, maxAttempts = 30): Promise<DatasetResponse> {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const dataset = await api.get(`datasets/${datasetId}/`).json<DatasetResponse>();
    if (dataset.status === "ready") return dataset;
    if (dataset.status === "error") throw new Error("Profiling failed");
  }
  throw new Error("Profiling timed out");
}

async function pollJob(
  jobId: string,
  onProgress?: (progress: number) => void,
  maxAttempts = 120,
): Promise<{ status: string; result_json: unknown }> {
  for (let i = 0; i < maxAttempts; i++) {
    await new Promise((r) => setTimeout(r, 3000));
    const job = await api.get(`jobs/${jobId}`).json<{
      status: string;
      progress: number;
      result_json: unknown;
      error_text: string | null;
    }>();
    if (job.status === "completed") return job;
    if (job.status === "failed") throw new Error(job.error_text ?? "Job failed");
    onProgress?.(job.progress ?? 0);
  }
  throw new Error("Job timed out");
}
