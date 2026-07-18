import { describe, it, expect, beforeEach } from "vitest";
import { useSessionStore, createMessage } from "./session-store";

beforeEach(() => {
  useSessionStore.setState({
    sessions: [],
    activeSessionId: null,
    messagesBySession: {},
    activeCleaningJobsBySession: {},
    workflowStateBySession: {},
  });
});

/* ── Session CRUD ──────────────────────────────────────────────────────── */

describe("SessionStore — createSession", () => {
  it("creates a session and sets it active", () => {
    const id = useSessionStore.getState().createSession("My session");
    const state = useSessionStore.getState();
    expect(state.sessions).toHaveLength(1);
    expect(state.sessions[0].title).toBe("My session");
    expect(state.activeSessionId).toBe(id);
  });

  it("defaults title to 'New session'", () => {
    useSessionStore.getState().createSession();
    expect(useSessionStore.getState().sessions[0].title).toBe("New session");
  });

  it("prepends new sessions to the list", () => {
    useSessionStore.getState().createSession("First");
    useSessionStore.getState().createSession("Second");
    expect(useSessionStore.getState().sessions[0].title).toBe("Second");
  });

  it("initialises an empty message list for the new session", () => {
    const id = useSessionStore.getState().createSession();
    expect(useSessionStore.getState().messagesBySession[id]).toEqual([]);
  });
});

describe("SessionStore — deleteSession", () => {
  it("removes the session from the list", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().deleteSession(id);
    expect(useSessionStore.getState().sessions).toHaveLength(0);
  });

  it("clears activeSessionId when deleting the active session", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().deleteSession(id);
    expect(useSessionStore.getState().activeSessionId).toBeNull();
  });

  it("preserves activeSessionId when deleting a different session", () => {
    const id1 = useSessionStore.getState().createSession("First");
    const id2 = useSessionStore.getState().createSession("Second");
    useSessionStore.getState().setActiveSession(id1);
    useSessionStore.getState().deleteSession(id2);
    expect(useSessionStore.getState().activeSessionId).toBe(id1);
  });

  it("removes the message list for the deleted session", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().deleteSession(id);
    expect(useSessionStore.getState().messagesBySession[id]).toBeUndefined();
  });
});

describe("SessionStore — renameSession", () => {
  it("updates the session title", () => {
    const id = useSessionStore.getState().createSession("Old");
    useSessionStore.getState().renameSession(id, "New");
    expect(useSessionStore.getState().sessions[0].title).toBe("New");
  });
});

describe("SessionStore — pinSession", () => {
  it("toggles pinned from false to true", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().pinSession(id);
    expect(useSessionStore.getState().sessions[0].pinned).toBe(true);
  });

  it("toggles pinned from true to false", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().pinSession(id);
    useSessionStore.getState().pinSession(id);
    expect(useSessionStore.getState().sessions[0].pinned).toBe(false);
  });
});

describe("SessionStore — setActiveSession", () => {
  it("sets the active session id", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().setActiveSession(null);
    expect(useSessionStore.getState().activeSessionId).toBeNull();
    useSessionStore.getState().setActiveSession(id);
    expect(useSessionStore.getState().activeSessionId).toBe(id);
  });
});

describe("SessionStore — setSessionDatasetId", () => {
  it("sets the datasetId on the session", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().setSessionDatasetId(id, "ds-123");
    expect(useSessionStore.getState().sessions[0].datasetId).toBe("ds-123");
  });
});

/* ── Messages ──────────────────────────────────────────────────────────── */

describe("SessionStore — addMessage", () => {
  it("appends a message to the session", () => {
    const sessionId = useSessionStore.getState().createSession();
    const msg = createMessage("user", "Hello");
    useSessionStore.getState().addMessage(sessionId, msg);
    expect(useSessionStore.getState().messagesBySession[sessionId]).toHaveLength(1);
  });

  it("preserves message order", () => {
    const sessionId = useSessionStore.getState().createSession();
    const m1 = createMessage("user", "First");
    const m2 = createMessage("assistant", "Second");
    useSessionStore.getState().addMessage(sessionId, m1);
    useSessionStore.getState().addMessage(sessionId, m2);
    const msgs = useSessionStore.getState().messagesBySession[sessionId];
    expect(msgs[0].content).toBe("First");
    expect(msgs[1].content).toBe("Second");
  });
});

describe("SessionStore — updateMessage", () => {
  it("updates content of an existing message", () => {
    const sessionId = useSessionStore.getState().createSession();
    const msg = createMessage("user", "Original");
    useSessionStore.getState().addMessage(sessionId, msg);
    useSessionStore.getState().updateMessage(sessionId, msg.id, { content: "Updated" });
    const msgs = useSessionStore.getState().messagesBySession[sessionId];
    expect(msgs[0].content).toBe("Updated");
  });

  it("leaves other messages untouched", () => {
    const sessionId = useSessionStore.getState().createSession();
    const m1 = createMessage("user", "Keep me");
    const m2 = createMessage("assistant", "Change me");
    useSessionStore.getState().addMessage(sessionId, m1);
    useSessionStore.getState().addMessage(sessionId, m2);
    useSessionStore.getState().updateMessage(sessionId, m2.id, { content: "Changed" });
    const msgs = useSessionStore.getState().messagesBySession[sessionId];
    expect(msgs[0].content).toBe("Keep me");
    expect(msgs[1].content).toBe("Changed");
  });
});

/* ── Workflow ──────────────────────────────────────────────────────────── */

describe("SessionStore — workflow", () => {
  const wf = (sessionId: string) =>
    useSessionStore.getState().workflowStateBySession[sessionId];

  it("startWorkflow sets a session's workflow with all steps pending", () => {
    useSessionStore.getState().startWorkflow("s1", "ds-1", "data.csv");
    expect(wf("s1").datasetId).toBe("ds-1");
    expect(wf("s1").datasetFilename).toBe("data.csv");
    expect(wf("s1").steps.every((s) => s.status === "pending")).toBe(true);
  });

  it("setWorkflowStep marks a step as active", () => {
    useSessionStore.getState().startWorkflow("s1", "ds-1", "data.csv");
    useSessionStore.getState().setWorkflowStep("s1", "plan", "active");
    expect(wf("s1").steps.find((s) => s.id === "plan")?.status).toBe("active");
  });

  it("setWorkflowStep marks prior steps as complete when advancing", () => {
    useSessionStore.getState().startWorkflow("s1", "ds-1", "data.csv");
    useSessionStore.getState().setWorkflowStep("s1", "clean", "active");
    const steps = wf("s1").steps;
    expect(steps.find((s) => s.id === "inspect")?.status).toBe("complete");
    expect(steps.find((s) => s.id === "plan")?.status).toBe("complete");
    expect(steps.find((s) => s.id === "clean")?.status).toBe("active");
    expect(steps.find((s) => s.id === "validate")?.status).toBe("pending");
  });

  it("setWorkflowStep marks a step as error", () => {
    useSessionStore.getState().startWorkflow("s1", "ds-1", "data.csv");
    useSessionStore.getState().setWorkflowStep("s1", "inspect", "error");
    expect(wf("s1").steps.find((s) => s.id === "inspect")?.status).toBe("error");
  });

  it("setWorkflowStep is a no-op when the session has no workflow", () => {
    expect(() => {
      useSessionStore.getState().setWorkflowStep("s1", "inspect", "active");
    }).not.toThrow();
    expect(wf("s1")).toBeUndefined();
  });

  it("clearWorkflow removes only that session's workflow", () => {
    useSessionStore.getState().startWorkflow("s1", "ds-1", "data.csv");
    useSessionStore.getState().clearWorkflow("s1");
    expect(wf("s1")).toBeUndefined();
  });

  it("keeps each session's workflow independent (no cross-clobbering)", () => {
    useSessionStore.getState().startWorkflow("s1", "ds-1", "a.csv");
    useSessionStore.getState().startWorkflow("s2", "ds-2", "b.csv");
    useSessionStore.getState().setWorkflowStep("s2", "clean", "active");

    // s2 advanced; s1 must be untouched.
    expect(wf("s1").steps.every((s) => s.status === "pending")).toBe(true);
    expect(wf("s2").steps.find((s) => s.id === "clean")?.status).toBe("active");

    // Clearing s2 leaves s1 intact.
    useSessionStore.getState().clearWorkflow("s2");
    expect(wf("s2")).toBeUndefined();
    expect(wf("s1").datasetId).toBe("ds-1");
  });

  it("deleteSession discards that session's workflow state", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().startWorkflow(id, "ds-1", "data.csv");
    useSessionStore.getState().deleteSession(id);
    expect(useSessionStore.getState().workflowStateBySession[id]).toBeUndefined();
  });
});

/* ── createMessage helper ──────────────────────────────────────────────── */

describe("createMessage", () => {
  it("creates a message with correct role and content", () => {
    const msg = createMessage("user", "Hello");
    expect(msg.role).toBe("user");
    expect(msg.content).toBe("Hello");
    expect(msg.card).toBeNull();
    expect(typeof msg.id).toBe("string");
    expect(typeof msg.timestamp).toBe("string");
  });

  it("accepts an optional card payload", () => {
    const card = {
      type: "data_overview" as const,
      rowCount: 10,
      colCount: 3,
      fileSizeBytes: 1024,
      nullPercentage: 0.5,
      columnTypes: { string: 2, number: 1 },
    };
    const msg = createMessage("assistant", "Here is your data", card);
    expect(msg.card).toEqual(card);
  });

  it("generates unique ids", () => {
    const ids = Array.from({ length: 20 }, () => createMessage("user", "x").id);
    expect(new Set(ids).size).toBe(20);
  });
});

/* ── Active cleaning jobs (re-attach after refresh) ────────────────────── */

describe("SessionStore — active cleaning jobs", () => {
  const job = {
    jobId: "job-1",
    datasetId: "ds-1",
    datasetFilename: "orders.csv",
    progressMessageId: "msg-1",
    rowsBefore: 100,
    steps: [{ operation: "deduplicate", column: null, params: {}, description: "Remove duplicate rows" }],
    startedAt: "2026-07-09T00:00:00.000Z",
  };

  it("registerCleaningJob stores the job keyed by session", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().registerCleaningJob(id, job);
    expect(useSessionStore.getState().activeCleaningJobsBySession[id]).toEqual(job);
  });

  it("clearCleaningJob removes only that session's job", () => {
    const a = useSessionStore.getState().createSession();
    const b = useSessionStore.getState().createSession();
    useSessionStore.getState().registerCleaningJob(a, job);
    useSessionStore.getState().registerCleaningJob(b, { ...job, jobId: "job-2" });
    useSessionStore.getState().clearCleaningJob(a);
    const state = useSessionStore.getState();
    expect(state.activeCleaningJobsBySession[a]).toBeUndefined();
    expect(state.activeCleaningJobsBySession[b]?.jobId).toBe("job-2");
  });

  it("deleteSession discards that session's active job", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().registerCleaningJob(id, job);
    useSessionStore.getState().deleteSession(id);
    expect(useSessionStore.getState().activeCleaningJobsBySession[id]).toBeUndefined();
  });

  it("persists active jobs so a refresh can re-attach (partialize)", () => {
    const id = useSessionStore.getState().createSession();
    useSessionStore.getState().registerCleaningJob(id, job);
    const persisted = JSON.parse(
      localStorage.getItem("datatiger-sessions") ?? "{}",
    ) as { state?: { activeCleaningJobsBySession?: Record<string, unknown> } };
    expect(persisted.state?.activeCleaningJobsBySession?.[id]).toBeTruthy();
  });
});
