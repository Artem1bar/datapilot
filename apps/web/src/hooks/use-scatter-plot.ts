import { useCallback, useState } from "react";
import { api } from "@/lib/api";
import { toMethodsCard } from "@/lib/analysis-methods";
import { describeScatterRequest, type ScatterRequest } from "@/lib/scatter";
import { useAppStore } from "@/stores/app-store";
import { createMessage, useSessionStore } from "@/stores/session-store";
import type { ChartConfig, TableResult } from "@/types";

/** The plot endpoint's reply: a chat turn's shape, without a chat session. */
export interface ScatterTurn {
  readonly answer: string;
  readonly charts?: readonly ChartConfig[];
  readonly tables?: readonly TableResult[];
  readonly provenance?: Parameters<typeof toMethodsCard>[0];
}

export interface ScatterOutcome {
  readonly ok: boolean;
  readonly error?: string;
}

/**
 * Record a plot in the conversation the way an analysis answer is recorded:
 * the answer, the chart as a card, and the methods note behind it — then the
 * chart in the panel. A plot the user asked for by name is still a computed
 * result with a denominator and a reproducible script.
 */
export function recordScatterTurn(sessionId: string, turn: ScatterTurn): void {
  const { addMessage } = useSessionStore.getState();
  const { addCharts, setChartPanelOpen } = useAppStore.getState();

  addMessage(sessionId, createMessage("assistant", turn.answer));

  const chart = turn.charts?.[0];
  if (chart) {
    addMessage(
      sessionId,
      createMessage("assistant", "", {
        type: "visualization",
        chart,
        description: null,
      }),
    );
    addCharts([chart]);
    setChartPanelOpen(true);
  }

  const methods = toMethodsCard(turn.provenance, turn.provenance?.question ?? "");
  if (methods) {
    addMessage(sessionId, createMessage("assistant", "", methods));
  }
}

/** Request a scatter plot of the active session's dataset. */
export function useScatterPlot() {
  const [plotting, setPlotting] = useState(false);

  const plot = useCallback(async (request: ScatterRequest): Promise<ScatterOutcome> => {
    const { activeSessionId, sessions, addMessage } = useSessionStore.getState();
    const session = sessions.find((entry) => entry.id === activeSessionId);
    if (!session?.datasetId) {
      return { ok: false, error: "Attach a dataset first." };
    }

    const sessionId = session.id;
    addMessage(sessionId, createMessage("user", describeScatterRequest(request)));
    setPlotting(true);
    try {
      const turn = await api
        .post(`analysis/${session.datasetId}/scatter`, {
          json: { x: request.x, y: request.y, color_by: request.colorBy, size: request.size },
          timeout: 180_000,
        })
        .json<ScatterTurn>();
      recordScatterTurn(sessionId, turn);
      return { ok: true };
    } catch (err) {
      const error = err instanceof Error ? err.message : "Unknown error";
      addMessage(sessionId, createMessage("system", `Scatter plot failed: ${error}`));
      return { ok: false, error };
    } finally {
      setPlotting(false);
    }
  }, []);

  return { plot, plotting };
}
