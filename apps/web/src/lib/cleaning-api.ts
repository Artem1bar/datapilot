import { api } from "./api";
import type { CleaningStep } from "@/types";
import type { OperationCatalog, PlanIssue } from "./plan-editor";

/**
 * The operation catalogue is static for the life of the deployment, so it is
 * fetched once and shared. Every review card renders its editor from it.
 */
let catalogPromise: Promise<OperationCatalog> | null = null;

export function getOperationCatalog(): Promise<OperationCatalog> {
  if (!catalogPromise) {
    // `async` deliberately: ky can throw synchronously (an unusable base URL),
    // and a throw during a component's mount effect would take the whole card
    // down instead of degrading to "step details unavailable".
    catalogPromise = (async () => api.get("cleaning/operations").json<OperationCatalog>())().catch(
      (error: unknown) => {
        // Don't cache a failure — the next card should try again.
        catalogPromise = null;
        throw error;
      },
    );
  }
  return catalogPromise;
}

/** Only for tests: forget the cached catalogue. */
export function resetOperationCatalog(): void {
  catalogPromise = null;
}

export interface PlanValidation {
  readonly valid: boolean;
  readonly issues: readonly PlanIssue[];
}

/**
 * Ask the server whether this edited plan can be applied to the dataset.
 *
 * The card validates locally as the user types; this is the authoritative
 * check, run before dispatch so a disagreement between the two surfaces as a
 * message in the card rather than a failed job.
 */
export function validatePlan(
  datasetId: string,
  steps: readonly CleaningStep[],
): Promise<PlanValidation> {
  return api
    .post(`cleaning/${datasetId}/plan/validate`, { json: { steps }, timeout: 30_000 })
    .json<PlanValidation>();
}
