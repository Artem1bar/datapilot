import type {
  AnalysisCodeScript,
  AnalysisMethodsPayload,
  AnalysisOperationRecord,
  ChartConfig,
  TableResult,
} from "@/types";

/** The code export as the API serializes it: one key per language, plus a
 *  `<language>_incomplete` list naming operations the dialect cannot express. */
type RawCode = Record<string, unknown>;

/** The provenance record as the API serializes it (snake_case, untrusted). */
interface RawProvenance {
  readonly question?: string;
  readonly dataset?: {
    filename?: string | null;
    rows?: number;
    columns?: number;
  };
  readonly operations?: readonly AnalysisOperationRecord[];
  readonly environment?: Record<string, string>;
  readonly multiple_comparisons?: AnalysisMethodsPayload["multipleComparisons"];
  readonly methods_note?: string;
  readonly code?: RawCode | null;
}

/** One assistant turn from the analysis endpoint. */
export interface AnalysisTurn {
  readonly role: string;
  readonly content: string;
  readonly charts?: ChartConfig[];
  /** Index-aligned with `provenance.operations` — both are built from the same
   *  list of executed results, in order. */
  readonly tables?: TableResult[];
  readonly provenance?: RawProvenance | null;
}

const LANGUAGES = [
  { key: "python", label: "Python" },
  { key: "r", label: "R" },
] as const;

/**
 * The exported scripts, in a stable order, skipping any the API did not send.
 *
 * Absence is normal rather than exceptional: a session recorded before code
 * export existed has no `code` key at all, and a dialect whose renderer failed
 * is omitted rather than sent empty. Both mean "offer nothing", not "offer an
 * empty editor".
 */
export function toCodeScripts(
  code: RawCode | null | undefined,
): AnalysisCodeScript[] {
  if (!code) return [];

  return LANGUAGES.flatMap(({ key, label }) => {
    const source = code[key];
    if (typeof source !== "string" || source.trim() === "") return [];
    const incomplete = code[`${key}_incomplete`];
    return [
      {
        language: key,
        label,
        source,
        incomplete: Array.isArray(incomplete) ? incomplete.map(String) : [],
      },
    ];
  });
}

/**
 * Turn the API's provenance record into a Methods card, or null when there is
 * nothing to show.
 *
 * Provenance is absent by design on a refused or failed analysis — there is no
 * computation to account for — and absent by accident on any client talking to
 * an older API. Both cases mean "render no card", not "render an empty one".
 */
export function toMethodsCard(
  provenance: RawProvenance | null | undefined,
  question = "",
): AnalysisMethodsPayload | null {
  if (!provenance || !provenance.operations?.length) return null;

  const environment = provenance.environment ?? {};
  return {
    type: "analysis_methods",
    question: provenance.question ?? question,
    dataset: {
      filename: provenance.dataset?.filename ?? null,
      rows: provenance.dataset?.rows ?? 0,
      columns: provenance.dataset?.columns ?? 0,
    },
    operations: provenance.operations,
    environment: {
      python: environment.python ?? "?",
      pandas: environment.pandas ?? "?",
      numpy: environment.numpy ?? "?",
      scipy: environment.scipy ?? "?",
    },
    multipleComparisons: provenance.multiple_comparisons ?? null,
    methodsNote: provenance.methods_note ?? "",
    code: toCodeScripts(provenance.code),
  };
}
