// @vitest-environment node
//
// ky needs an absolute base URL outside a browser, so these tests run in Node
// with VITE_API_URL stubbed to a fake origin and `fetch` mocked.
import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

const ORIGIN = "https://api.test";

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "content-type": "application/json" },
  });
}

function html(status = 200): Response {
  return new Response("<!doctype html><html><body>SPA</body></html>", {
    status,
    headers: { "content-type": "text/html; charset=utf-8" },
  });
}

const fetchMock = vi.fn<typeof fetch>();

async function loadApi() {
  vi.resetModules();
  vi.stubEnv("VITE_API_URL", ORIGIN);
  return await import("./api");
}

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("api client — answers that did not come from the API", () => {
  it("rejects a GET answered with HTML (a static host's SPA fallback) and does not retry", async () => {
    const { api, ApiUnavailableError } = await loadApi();
    fetchMock.mockResolvedValue(html());

    const err = await api.get("datasets/abc").json().catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiUnavailableError);
    expect((err as InstanceType<typeof ApiUnavailableError>).kind).toBe("missing");
    expect((err as Error).message).toContain(
      `${ORIGIN} answered with a web page, not the DataPilot API`,
    );
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("rejects a POST answered with a bodiless 405 (no API behind the host)", async () => {
    const { api, ApiUnavailableError } = await loadApi();
    fetchMock.mockResolvedValue(new Response(null, { status: 405 }));

    const err = await api
      .post("datasets/upload", { body: new FormData() })
      .json()
      .catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiUnavailableError);
    expect((err as Error).message).toContain("not the DataPilot API");
  });

  it("reports the API as unreachable when a proxy answers with a bodiless 502", async () => {
    const { api, ApiUnavailableError } = await loadApi();
    fetchMock.mockResolvedValue(
      new Response("", { status: 502, headers: { "content-type": "text/plain" } }),
    );

    const err = await api.post("datasets/upload").json().catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiUnavailableError);
    expect((err as InstanceType<typeof ApiUnavailableError>).kind).toBe("unreachable");
    expect((err as Error).message).toContain(`Could not reach the DataPilot API at ${ORIGIN}`);
  });

  it("passes a real API 503 through with its detail", async () => {
    const { api, ApiUnavailableError } = await loadApi();
    fetchMock.mockResolvedValue(json({ detail: "AI features are disabled" }, 503));

    const err = await api.post("analysis/ds/chat").json().catch((e: unknown) => e);

    expect(err).not.toBeInstanceOf(ApiUnavailableError);
    expect((err as Error).message).toBe("AI features are disabled");
  });

  it("passes a real API 405 through with its detail", async () => {
    const { api, ApiUnavailableError } = await loadApi();
    fetchMock.mockResolvedValue(json({ detail: "Method Not Allowed" }, 405));

    const err = await api.post("datasets/upload").json().catch((e: unknown) => e);

    expect(err).not.toBeInstanceOf(ApiUnavailableError);
    expect((err as Error).message).toBe("Method Not Allowed");
  });

  it("names the origin when the network request itself fails", async () => {
    const { api, ApiUnavailableError } = await loadApi();
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const err = await api.get("datasets/abc").json().catch((e: unknown) => e);

    expect(err).toBeInstanceOf(ApiUnavailableError);
    expect((err as InstanceType<typeof ApiUnavailableError>).kind).toBe("unreachable");
    expect((err as Error).message).toContain(
      `Could not reach the DataPilot API at ${ORIGIN}`,
    );
    expect((err as Error).cause).toBeInstanceOf(TypeError);
  });

  it("leaves an abort alone so ky can report its own timeout", async () => {
    const { api, ApiUnavailableError } = await loadApi();
    const abort = new Error("aborted");
    abort.name = "AbortError";
    fetchMock.mockRejectedValue(abort);

    const err = await api.get("datasets/abc").json().catch((e: unknown) => e);

    expect(err).not.toBeInstanceOf(ApiUnavailableError);
    expect((err as Error).name).toBe("AbortError");
  });
});

describe("api client — real API errors", () => {
  it("surfaces a string detail", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(json({ detail: "Dataset not found" }, 404));

    await expect(api.get("datasets/missing").json()).rejects.toThrow(
      "Dataset not found",
    );
  });

  it("flattens a structured detail with issues", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(
      json(
        { detail: { message: "Recipe incompatible", issues: ["no column a", "no column b"] } },
        409,
      ),
    );

    await expect(api.post("recipes/r1/apply").json()).rejects.toThrow(
      "Recipe incompatible no column a; no column b",
    );
  });

  it("returns JSON from a healthy API and builds the URL from VITE_API_URL", async () => {
    const { api } = await loadApi();
    fetchMock.mockResolvedValue(json({ id: "ds-1" }));

    await expect(api.get("datasets/ds-1").json()).resolves.toEqual({ id: "ds-1" });
    const request = fetchMock.mock.calls[0][0] as Request;
    expect(request.url).toBe(`${ORIGIN}/api/v1/datasets/ds-1`);
  });
});
