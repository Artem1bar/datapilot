import ky from "ky";
import {
  apiLocation,
  describeApiProblem,
  isApiCspViolation,
  isBareNotFound,
  isGatewayFailure,
  isHtmlContentType,
  pageOrigin,
  type ApiProblemKind,
} from "./api-base";

/**
 * In development: Vite proxy forwards /api → the local backend.
 * In production:  VITE_API_URL is the deployed API's origin (see api-base.ts).
 */

/**
 * Thrown when nothing answered as the DataPilot API: the request never got
 * out (network, CSP), or what answered was a static host or proxy rather
 * than the API. The message names the origin tried and the setting that
 * fixes it.
 */
export class ApiUnavailableError extends Error {
  readonly kind: ApiProblemKind;

  constructor(kind: ApiProblemKind, options?: ErrorOptions) {
    super(describeApiProblem(kind, apiLocation, pageOrigin), options);
    this.name = "ApiUnavailableError";
    this.kind = kind;
  }
}

/** Minimal shape of the Clerk singleton exposed on window once ClerkProvider mounts. */
interface ClerkGlobal {
  session?: { getToken?: () => Promise<string | null> };
}

function isAbort(error: unknown): boolean {
  return error instanceof Error && error.name === "AbortError";
}

/** Let a CSP report queued behind a failed fetch land before we judge it. */
function nextTask(): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, 0));
}

/** fetch that turns a failure to connect into a message about *this* API. */
async function fetchApi(
  input: RequestInfo | URL,
  init?: RequestInit,
): Promise<Response> {
  let blockedByCsp = false;
  const onViolation = (event: Event) => {
    if (isApiCspViolation(event as SecurityPolicyViolationEvent)) {
      blockedByCsp = true;
    }
  };
  const doc = typeof document === "undefined" ? undefined : document;
  doc?.addEventListener("securitypolicyviolation", onViolation);
  try {
    return await fetch(input, init);
  } catch (error) {
    // ky's timeout or the caller's signal — not ours to relabel.
    if (isAbort(error)) throw error;
    await nextTask();
    throw new ApiUnavailableError(blockedByCsp ? "blocked" : "unreachable", {
      cause: error,
    });
  } finally {
    doc?.removeEventListener("securitypolicyviolation", onViolation);
  }
}

export const api = ky.create({
  prefixUrl: apiLocation.base,
  fetch: fetchApi,
  timeout: 180_000, // 3 min — AI calls can take 30-60s
  retry: {
    limit: 1,
    methods: ["get"],
    statusCodes: [408, 429],
    backoffLimit: 2000,
    // Retrying will not make an absent API appear.
    shouldRetry: ({ error }) =>
      error instanceof ApiUnavailableError ? false : undefined,
  },
  hooks: {
    beforeRequest: [
      async (request) => {
        // Attach the Clerk session token when Clerk is active (production auth).
        // In dev without Clerk this is a no-op; the backend uses DEV_AUTH_BYPASS.
        const clerk = (globalThis as unknown as { Clerk?: ClerkGlobal }).Clerk;
        const token = await clerk?.session?.getToken?.();
        if (token) {
          request.headers.set("Authorization", `Bearer ${token}`);
        }
      },
    ],
    afterResponse: [
      async (_request, _options, response) => {
        // The API never sends HTML, and its 404/405s carry a JSON `detail`.
        // A static host with no backend (Vercel serving only the frontend)
        // answers a GET with the SPA's HTML and a POST with a bodiless 405 —
        // fail those with a message that names the problem instead of
        // leaving `.json()` to choke on "<!doctype".
        const contentType = response.headers.get("content-type");
        if (isHtmlContentType(contentType)) {
          throw new ApiUnavailableError("missing");
        }
        // A proxy's own 502/503/504 (no JSON) means the API behind it is down.
        if (isGatewayFailure(response.status, contentType)) {
          throw new ApiUnavailableError("unreachable");
        }
        if (response.status === 404 || response.status === 405) {
          const text = await response
            .clone()
            .text()
            .catch(() => "");
          if (isBareNotFound(response.status, text)) {
            throw new ApiUnavailableError("missing");
          }
        }
      },
    ],
    beforeError: [
      async (error) => {
        const { response } = error;
        try {
          const body = (await response.clone().json()) as {
            detail?: string | { message?: string; issues?: string[] };
          };
          if (typeof body?.detail === "string") {
            error.message = body.detail;
          } else if (body?.detail?.message) {
            // Structured errors (e.g. recipe compatibility) carry an issue list.
            const issues = body.detail.issues?.length
              ? ` ${body.detail.issues.join("; ")}`
              : "";
            error.message = `${body.detail.message}${issues}`;
          }
        } catch {
          // ignore parse errors — use default message
        }
        return error;
      },
    ],
  },
});
