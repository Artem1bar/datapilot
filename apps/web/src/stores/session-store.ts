import { create } from "zustand";
import { persist } from "zustand/middleware";
import type { Session, ChatMessageV2, WorkflowState, WorkflowStepId } from "@/types";

/* ── Helpers ────────────────────────────────────────────────────────────── */

const DEFAULT_WORKFLOW_STEPS = [
  { id: "inspect" as const, label: "Inspect", status: "pending" as const },
  { id: "plan" as const, label: "Plan", status: "pending" as const },
  { id: "clean" as const, label: "Clean", status: "pending" as const },
  { id: "validate" as const, label: "Validate", status: "pending" as const },
];

function generateId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function nowIso(): string {
  return new Date().toISOString();
}

/* ── State ──────────────────────────────────────────────────────────────── */

interface SessionState {
  sessions: readonly Session[];
  activeSessionId: string | null;
  messagesBySession: Readonly<Record<string, readonly ChatMessageV2[]>>;
  // Keyed by session id: each session runs its own cleaning workflow, so a
  // second run in another session no longer clobbers the first.
  workflowStateBySession: Readonly<Record<string, WorkflowState>>;

  // Session actions
  createSession: (title?: string) => string;
  deleteSession: (id: string) => void;
  renameSession: (id: string, title: string) => void;
  pinSession: (id: string) => void;
  setActiveSession: (id: string | null) => void;
  setSessionDatasetId: (sessionId: string, datasetId: string) => void;

  // Message actions
  addMessage: (sessionId: string, message: ChatMessageV2) => void;
  updateMessage: (sessionId: string, messageId: string, updates: Partial<ChatMessageV2>) => void;

  // Workflow actions (scoped to a session)
  startWorkflow: (sessionId: string, datasetId: string, filename: string) => void;
  setWorkflowStep: (
    sessionId: string,
    stepId: WorkflowStepId,
    status: "active" | "complete" | "error",
  ) => void;
  clearWorkflow: (sessionId: string) => void;
}

export const useSessionStore = create<SessionState>()(
  persist(
    (set, get) => ({
      sessions: [],
      activeSessionId: null,
      messagesBySession: {},
      workflowStateBySession: {},

      /* ── Session CRUD ─────────────────────────────────────────── */

      createSession: (title) => {
        const id = generateId();
        const now = nowIso();
        const session: Session = {
          id,
          title: title ?? "New session",
          subtitle: "",
          createdAt: now,
          updatedAt: now,
          pinned: false,
          datasetId: null,
        };
        set((state) => ({
          sessions: [session, ...state.sessions],
          activeSessionId: id,
          messagesBySession: { ...state.messagesBySession, [id]: [] },
        }));
        return id;
      },

      deleteSession: (id) =>
        set((state) => {
          const { [id]: _removed, ...rest } = state.messagesBySession;
          const { [id]: _wf, ...restWf } = state.workflowStateBySession;
          return {
            sessions: state.sessions.filter((s) => s.id !== id),
            activeSessionId: state.activeSessionId === id ? null : state.activeSessionId,
            messagesBySession: rest,
            workflowStateBySession: restWf,
          };
        }),

      renameSession: (id, title) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id ? { ...s, title, updatedAt: nowIso() } : s,
          ),
        })),

      pinSession: (id) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === id ? { ...s, pinned: !s.pinned } : s,
          ),
        })),

      setActiveSession: (id) => set({ activeSessionId: id }),

      setSessionDatasetId: (sessionId, datasetId) =>
        set((state) => ({
          sessions: state.sessions.map((s) =>
            s.id === sessionId ? { ...s, datasetId, updatedAt: nowIso() } : s,
          ),
        })),

      /* ── Messages ─────────────────────────────────────────────── */

      addMessage: (sessionId, message) =>
        set((state) => {
          const existing = state.messagesBySession[sessionId] ?? [];
          return {
            messagesBySession: {
              ...state.messagesBySession,
              [sessionId]: [...existing, message],
            },
            sessions: state.sessions.map((s) =>
              s.id === sessionId ? { ...s, updatedAt: nowIso() } : s,
            ),
          };
        }),

      updateMessage: (sessionId, messageId, updates) =>
        set((state) => {
          const existing = state.messagesBySession[sessionId] ?? [];
          return {
            messagesBySession: {
              ...state.messagesBySession,
              [sessionId]: existing.map((m) =>
                m.id === messageId ? { ...m, ...updates } : m,
              ),
            },
          };
        }),

      /* ── Workflow ──────────────────────────────────────────────── */

      startWorkflow: (sessionId, datasetId, filename) =>
        set((state) => ({
          workflowStateBySession: {
            ...state.workflowStateBySession,
            [sessionId]: {
              datasetId,
              datasetFilename: filename,
              steps: DEFAULT_WORKFLOW_STEPS.map((s) => ({ ...s })),
            },
          },
        })),

      setWorkflowStep: (sessionId, stepId, status) => {
        const current = get().workflowStateBySession[sessionId];
        if (!current) return;

        set((state) => ({
          workflowStateBySession: {
            ...state.workflowStateBySession,
            [sessionId]: {
              ...current,
              steps: current.steps.map((s) => {
                if (s.id === stepId) return { ...s, status };
                // Mark all prior steps as complete if advancing
                if (status === "active") {
                  const stepOrder: WorkflowStepId[] = ["inspect", "plan", "clean", "validate"];
                  const targetIdx = stepOrder.indexOf(stepId);
                  const thisIdx = stepOrder.indexOf(s.id);
                  if (thisIdx < targetIdx && s.status !== "error") {
                    return { ...s, status: "complete" };
                  }
                }
                return s;
              }),
            },
          },
        }));
      },

      clearWorkflow: (sessionId) =>
        set((state) => {
          const { [sessionId]: _removed, ...rest } = state.workflowStateBySession;
          return { workflowStateBySession: rest };
        }),
    }),
    {
      name: "datatiger-sessions",
      partialize: (state) => ({
        sessions: state.sessions,
        activeSessionId: state.activeSessionId,
        messagesBySession: state.messagesBySession,
      }),
    },
  ),
);

/* ── Helpers for creating messages ──────────────────────────────────────── */

export function createMessage(
  role: ChatMessageV2["role"],
  content: string,
  card: ChatMessageV2["card"] = null,
): ChatMessageV2 {
  return {
    id: generateId(),
    role,
    content,
    card,
    timestamp: nowIso(),
  };
}
