import { describe, it, expect } from "vitest";
import {
  classifyHealth,
  describeApiProblem,
  isApiCspViolation,
  isBareNotFound,
  isGatewayFailure,
  isHtmlContentType,
  isJsonContentType,
  resolveApiLocation,
} from "./api-base";

const PAGE = "https://datapilot-eight.vercel.app";

describe("resolveApiLocation", () => {
  it("falls back to the page's own origin when VITE_API_URL is unset", () => {
    for (const value of [undefined, "", "   "]) {
      expect(resolveApiLocation(value, PAGE)).toEqual({
        base: "/api/v1",
        healthUrl: `${PAGE}/health`,
        origin: PAGE,
        sameOrigin: true,
      });
    }
  });

  it("uses a configured origin and appends the API prefix", () => {
    expect(resolveApiLocation("https://api.example.com", PAGE)).toEqual({
      base: "https://api.example.com/api/v1",
      healthUrl: "https://api.example.com/health",
      origin: "https://api.example.com",
      sameOrigin: false,
    });
  });

  it("tolerates whitespace, trailing slashes and a pasted /api/v1 suffix", () => {
    for (const value of [
      " https://api.example.com/ ",
      "https://api.example.com/api/v1",
      "https://api.example.com/api/v1/",
      "https://api.example.com//",
    ]) {
      expect(resolveApiLocation(value, PAGE).base).toBe(
        "https://api.example.com/api/v1",
      );
    }
  });

  it("keeps a reverse-proxy path prefix", () => {
    const loc = resolveApiLocation("https://example.com/datapilot/", PAGE);
    expect(loc.base).toBe("https://example.com/datapilot/api/v1");
    expect(loc.healthUrl).toBe("https://example.com/datapilot/health");
  });

  it("assumes https when the scheme is missing", () => {
    expect(resolveApiLocation("api.example.com", PAGE).origin).toBe(
      "https://api.example.com",
    );
    expect(resolveApiLocation("http://localhost:8000", PAGE).origin).toBe(
      "http://localhost:8000",
    );
  });

  it("ignores a value that is not a URL but remembers it for the message", () => {
    const loc = resolveApiLocation("not a url", PAGE);
    expect(loc.sameOrigin).toBe(true);
    expect(loc.base).toBe("/api/v1");
    expect(loc.invalidValue).toBe("not a url");
  });
});

describe("recognising answers that did not come from the API", () => {
  it("isHtmlContentType", () => {
    expect(isHtmlContentType("text/html; charset=utf-8")).toBe(true);
    expect(isHtmlContentType("TEXT/HTML")).toBe(true);
    expect(isHtmlContentType("application/json")).toBe(false);
    expect(isHtmlContentType("text/csv")).toBe(false);
    expect(isHtmlContentType(null)).toBe(false);
  });

  it("isBareNotFound: only a bodiless 404/405 — FastAPI's carry a JSON detail", () => {
    expect(isBareNotFound(405, "")).toBe(true);
    expect(isBareNotFound(404, "  \n")).toBe(true);
    expect(isBareNotFound(405, '{"detail":"Method Not Allowed"}')).toBe(false);
    expect(isBareNotFound(500, "")).toBe(false);
    expect(isBareNotFound(200, "")).toBe(false);
  });

  it("isGatewayFailure: a non-JSON 502/503/504 is a proxy, not the API", () => {
    expect(isGatewayFailure(502, "text/plain")).toBe(true);
    expect(isGatewayFailure(503, null)).toBe(true);
    expect(isGatewayFailure(504, "text/html")).toBe(true);
    expect(isGatewayFailure(503, "application/json")).toBe(false);
    expect(isGatewayFailure(500, "text/plain")).toBe(false);
    expect(isJsonContentType("application/problem+json")).toBe(true);
    expect(isJsonContentType("text/json")).toBe(false);
  });

  it("classifyHealth", () => {
    expect(classifyHealth(200, "application/json", '{"status":"ok"}')).toBe("ok");
    expect(classifyHealth(503, "application/json", '{"detail":"down"}')).toBe("ok");
    expect(classifyHealth(200, "text/html; charset=utf-8", "<!doctype html>")).toBe("missing");
    expect(classifyHealth(404, "text/html", "<!doctype html>")).toBe("missing");
    expect(classifyHealth(502, "text/html", "<h1>Bad gateway</h1>")).toBe("unreachable");
    expect(classifyHealth(502, "text/plain", "")).toBe("unreachable");
    expect(classifyHealth(200, "text/plain", "hello")).toBe("missing");
    expect(classifyHealth(200, "application/json", "null")).toBe("missing");
  });

  it("isApiCspViolation matches connect-src reports against the API host", () => {
    const loc = resolveApiLocation("https://api.example.com/prefix", PAGE);
    expect(
      isApiCspViolation(
        { violatedDirective: "connect-src", blockedURI: "https://api.example.com/health" },
        loc,
      ),
    ).toBe(true);
    expect(
      isApiCspViolation(
        { violatedDirective: "connect-src", blockedURI: "https://api.example.com" },
        loc,
      ),
    ).toBe(true);
    expect(
      isApiCspViolation(
        { violatedDirective: "style-src-elem", blockedURI: "https://api.example.com" },
        loc,
      ),
    ).toBe(false);
    expect(
      isApiCspViolation(
        { violatedDirective: "connect-src", blockedURI: "https://other.example.com" },
        loc,
      ),
    ).toBe(false);
    expect(isApiCspViolation({}, loc)).toBe(false);
    expect(
      isApiCspViolation(
        { violatedDirective: "connect-src", blockedURI: "https://x" },
        resolveApiLocation(undefined, ""),
      ),
    ).toBe(false);
  });
});

describe("describeApiProblem", () => {
  it("names the deployment gap when the app is calling its own origin", () => {
    const msg = describeApiProblem("missing", resolveApiLocation(undefined, PAGE), PAGE);
    expect(msg).toContain(`No DataPilot API is running at ${PAGE}`);
    expect(msg).toContain("Set VITE_API_URL");
    expect(msg).toContain("docs/DEPLOYMENT.md");
  });

  it("suspects the configured origin when one was given", () => {
    const msg = describeApiProblem(
      "missing",
      resolveApiLocation("https://datapilot-eight.vercel.app", PAGE),
      PAGE,
    );
    expect(msg).toContain("answered with a web page, not the DataPilot API");
    expect(msg).toContain("VITE_API_URL is the API's origin");
  });

  it("points at CORS_ORIGINS when the API could not be reached", () => {
    const msg = describeApiProblem(
      "unreachable",
      resolveApiLocation("https://api.example.com", PAGE),
      PAGE,
    );
    expect(msg).toContain("Could not reach the DataPilot API at https://api.example.com");
    expect(msg).toContain(`CORS_ORIGINS includes ${PAGE}`);
  });

  it("points at connect-src when the browser blocked the request", () => {
    const msg = describeApiProblem(
      "blocked",
      resolveApiLocation("https://api.example.com", PAGE),
      PAGE,
    );
    expect(msg).toContain("connect-src in vercel.json");
  });

  it("mentions an ignored, malformed VITE_API_URL", () => {
    const msg = describeApiProblem("missing", resolveApiLocation("nope nope", PAGE), PAGE);
    expect(msg).toContain('VITE_API_URL is set to "nope nope"');
  });
});
