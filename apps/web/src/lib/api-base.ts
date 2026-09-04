/**
 * Where the API lives, and how to describe it when it is not there.
 *
 * `VITE_API_URL` is the API's origin (https://api.example.com). Unset,
 * requests go to the page's own origin — right in dev, where the Vite proxy
 * forwards /api to the backend, and wrong on a static host such as Vercel,
 * which has no API and answers a GET with the SPA's HTML and a POST with a
 * bodiless 405.
 */

export const API_PATH_PREFIX = "/api/v1";

export interface ApiLocation {
  /** Prefix for API requests: "https://api.example.com/api/v1" or "/api/v1". */
  base: string;
  /** The API's root health check, absolute whenever the page has an origin. */
  healthUrl: string;
  /** Origin (plus any path prefix) the API is expected at — for messages. */
  origin: string;
  /** No VITE_API_URL: requests go to the page's own origin. */
  sameOrigin: boolean;
  /** VITE_API_URL was set to something that is not a URL, so it was ignored. */
  invalidValue?: string;
}

const HAS_SCHEME = /^[a-z][a-z0-9+.-]*:\/\//i;

export function resolveApiLocation(
  envUrl: string | undefined,
  pageOrigin: string,
): ApiLocation {
  const raw = (envUrl ?? "").trim();
  const sameOrigin: ApiLocation = {
    base: API_PATH_PREFIX,
    healthUrl: `${pageOrigin}/health`,
    origin: pageOrigin,
    sameOrigin: true,
  };
  if (!raw) return sameOrigin;

  let url: URL;
  try {
    url = new URL(HAS_SCHEME.test(raw) ? raw : `https://${raw}`);
  } catch {
    return { ...sameOrigin, invalidValue: raw };
  }
  // Tolerate trailing slashes and a pasted "/api/v1" suffix; keep any other
  // path so the API can sit behind a reverse-proxy prefix.
  const path = url.pathname
    .replace(/\/+$/, "")
    .replace(/\/api\/v1$/, "")
    .replace(/\/+$/, "");
  const origin = `${url.origin}${path}`;
  return {
    base: `${origin}${API_PATH_PREFIX}`,
    healthUrl: `${origin}/health`,
    origin,
    sameOrigin: false,
  };
}

export type ApiProblemKind = "missing" | "unreachable" | "blocked";

export function isHtmlContentType(
  contentType: string | null | undefined,
): boolean {
  return /^\s*text\/html\b/i.test(contentType ?? "");
}

export function isJsonContentType(
  contentType: string | null | undefined,
): boolean {
  return /^\s*application\/(problem\+)?json\b/i.test(contentType ?? "");
}

/**
 * A 502/503/504 without a JSON body is a proxy answering for an API that is
 * down, not the API itself — FastAPI's own 503s carry a JSON `detail`.
 */
export function isGatewayFailure(
  status: number,
  contentType: string | null | undefined,
): boolean {
  return (
    (status === 502 || status === 503 || status === 504) &&
    !isJsonContentType(contentType)
  );
}

/**
 * A 404/405 with no body came from a static host or proxy, not from FastAPI,
 * which always answers those with a JSON `detail`.
 */
export function isBareNotFound(status: number, bodyText: string): boolean {
  return (status === 404 || status === 405) && bodyText.trim() === "";
}

/**
 * What answered `GET /health`. JSON of any status is the API talking (even
 * if unhappily); anything else with a 5xx is a proxy fronting a dead API;
 * anything else at all is not the API.
 */
export function classifyHealth(
  status: number,
  contentType: string | null | undefined,
  bodyText: string,
): "ok" | ApiProblemKind {
  if (!isHtmlContentType(contentType)) {
    try {
      const body: unknown = JSON.parse(bodyText);
      if (typeof body === "object" && body !== null) return "ok";
    } catch {
      // not JSON — decided below
    }
  }
  return status >= 500 ? "unreachable" : "missing";
}

/** Origin of the API host alone (no path prefix), as CSP reports name it. */
function apiHostOrigin(location: ApiLocation): string {
  try {
    return new URL(location.healthUrl).origin;
  } catch {
    return "";
  }
}

/** True when a CSP report says `connect-src` blocked a request to the API. */
export function isApiCspViolation(
  event: { violatedDirective?: string; blockedURI?: string },
  location: ApiLocation = apiLocation,
): boolean {
  const host = apiHostOrigin(location);
  return (
    host !== "" &&
    (event.violatedDirective ?? "").startsWith("connect-src") &&
    (event.blockedURI ?? "").startsWith(host)
  );
}

export function describeApiProblem(
  kind: ApiProblemKind,
  location: ApiLocation,
  pageOrigin: string,
): string {
  const ignored = location.invalidValue
    ? `VITE_API_URL is set to "${location.invalidValue}", which is not a URL, so it was ignored. `
    : "";
  switch (kind) {
    case "missing":
      return location.sameOrigin
        ? `${ignored}No DataPilot API is running at ${location.origin} — this deployment serves the web app only. Set VITE_API_URL to the API's origin and redeploy (see docs/DEPLOYMENT.md).`
        : `${location.origin} answered with a web page, not the DataPilot API. Check that VITE_API_URL is the API's origin, not the web app's.`;
    case "unreachable":
      return `${ignored}Could not reach the DataPilot API at ${location.origin}. Check that the API is running and that its CORS_ORIGINS includes ${pageOrigin || "this site's origin"}.`;
    case "blocked":
      return `The browser blocked requests to ${location.origin}: this page's Content-Security-Policy (connect-src in vercel.json) does not list that origin. Add it and redeploy.`;
  }
}

/** The page's own origin; empty outside a browser. */
export const pageOrigin: string =
  typeof location === "undefined" ? "" : location.origin;

/** Resolved once at load from the build-time VITE_API_URL. */
export const apiLocation: ApiLocation = resolveApiLocation(
  import.meta.env.VITE_API_URL,
  pageOrigin,
);
