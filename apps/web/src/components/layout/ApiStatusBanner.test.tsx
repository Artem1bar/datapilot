import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiStatusBanner } from "./ApiStatusBanner";
import { useApiStatus, type ApiStatus } from "@/hooks/use-api-status";

vi.mock("@/hooks/use-api-status", () => ({ useApiStatus: vi.fn() }));

const mockStatus = (status: ApiStatus, recheck = vi.fn()) => {
  vi.mocked(useApiStatus).mockReturnValue({ status, recheck });
  return recheck;
};

beforeEach(() => vi.mocked(useApiStatus).mockReset());

describe("ApiStatusBanner", () => {
  it("renders nothing while checking or when the API answers", () => {
    mockStatus({ state: "checking" });
    const { container, rerender } = render(<ApiStatusBanner />);
    expect(container).toBeEmptyDOMElement();

    mockStatus({ state: "ok" });
    rerender(<ApiStatusBanner />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the problem and shows the diagnostic message", () => {
    mockStatus({
      state: "problem",
      kind: "missing",
      message: "No DataPilot API is running at https://x — set VITE_API_URL.",
    });
    render(<ApiStatusBanner />);

    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Backend not connected");
    expect(alert).toHaveTextContent("set VITE_API_URL");
  });

  it.each([
    ["unreachable", "Backend unreachable"],
    ["blocked", "Backend blocked by this page's security policy"],
  ] as const)("titles a %s problem", (kind, title) => {
    mockStatus({ state: "problem", kind, message: "m" });
    render(<ApiStatusBanner />);
    expect(screen.getByRole("alert")).toHaveTextContent(title);
  });

  it("Retry probes again", async () => {
    const recheck = mockStatus({ state: "problem", kind: "unreachable", message: "m" });
    render(<ApiStatusBanner />);

    await userEvent.setup().click(screen.getByRole("button", { name: /retry/i }));

    expect(recheck).toHaveBeenCalledTimes(1);
  });
});
