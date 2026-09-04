import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { act, renderHook, waitFor } from "@testing-library/react";
import { useApiStatus } from "./use-api-status";

// jsdom's page origin — what the hook probes when VITE_API_URL is unset.
const PAGE = window.location.origin;

function answer(body: string, contentType: string, status = 200) {
  return {
    status,
    headers: {
      get: (name: string) =>
        name.toLowerCase() === "content-type" ? contentType : null,
    },
    text: async () => body,
  };
}

const fetchMock = vi.fn();

beforeEach(() => {
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("useApiStatus", () => {
  it("starts checking and settles on ok when /health answers JSON", async () => {
    fetchMock.mockResolvedValue(answer('{"status":"ok"}', "application/json"));

    const { result } = renderHook(() => useApiStatus());
    expect(result.current.status.state).toBe("checking");

    await waitFor(() => expect(result.current.status.state).toBe("ok"));
    expect(fetchMock).toHaveBeenCalledWith(
      `${PAGE}/health`,
      expect.objectContaining({ headers: { Accept: "application/json" } }),
    );
  });

  it("reports a missing backend when the page's own origin answers with HTML", async () => {
    fetchMock.mockResolvedValue(answer("<!doctype html>", "text/html; charset=utf-8"));

    const { result } = renderHook(() => useApiStatus());

    await waitFor(() => expect(result.current.status.state).toBe("problem"));
    const status = result.current.status;
    if (status.state !== "problem") throw new Error("unreachable");
    expect(status.kind).toBe("missing");
    expect(status.message).toContain(`No DataPilot API is running at ${PAGE}`);
    expect(status.message).toContain("Set VITE_API_URL");
  });

  it("reports unreachable when the request fails", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useApiStatus());

    await waitFor(() => expect(result.current.status.state).toBe("problem"));
    const status = result.current.status;
    if (status.state !== "problem") throw new Error("unreachable");
    expect(status.kind).toBe("unreachable");
    expect(status.message).toContain("Could not reach the DataPilot API");
  });

  it("upgrades to blocked when a CSP report names the API host", async () => {
    fetchMock.mockRejectedValue(new TypeError("Failed to fetch"));

    const { result } = renderHook(() => useApiStatus());
    await waitFor(() => expect(result.current.status.state).toBe("problem"));

    act(() => {
      const event = Object.assign(new Event("securitypolicyviolation"), {
        violatedDirective: "connect-src",
        blockedURI: `${PAGE}/health`,
      });
      document.dispatchEvent(event);
    });

    const status = result.current.status;
    if (status.state !== "problem") throw new Error("unreachable");
    expect(status.kind).toBe("blocked");
    expect(status.message).toContain("connect-src in vercel.json");
  });

  it("recheck probes again and can recover", async () => {
    fetchMock.mockResolvedValueOnce(answer("<!doctype html>", "text/html"));
    fetchMock.mockResolvedValueOnce(answer('{"status":"ok"}', "application/json"));

    const { result } = renderHook(() => useApiStatus());
    await waitFor(() => expect(result.current.status.state).toBe("problem"));

    act(() => result.current.recheck());
    expect(result.current.status.state).toBe("checking");

    await waitFor(() => expect(result.current.status.state).toBe("ok"));
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("ignores an answer that arrives after unmount", async () => {
    let resolve!: (value: unknown) => void;
    fetchMock.mockReturnValue(new Promise((r) => (resolve = r)));

    const { result, unmount } = renderHook(() => useApiStatus());
    unmount();
    resolve(answer("<!doctype html>", "text/html"));
    await Promise.resolve();

    expect(result.current.status.state).toBe("checking");
  });
});
