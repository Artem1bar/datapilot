import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { AnalysisCodeExport } from "./AnalysisCodeExport";
import { toCodeScripts } from "@/lib/analysis-methods";
import { RAW_CODE } from "@/test/analysis-fixtures";

/** userEvent installs its own clipboard stub; override it after setup. */
function stubClipboard() {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  return writeText;
}

describe("toCodeScripts", () => {
  it("maps the API's code object onto ordered scripts", () => {
    const scripts = toCodeScripts(RAW_CODE);
    expect(scripts.map((script) => script.language)).toEqual(["python", "r"]);
    expect(scripts[0].source).toContain("import pandas as pd");
    expect(scripts[1].incomplete).toEqual(["quantile_regression"]);
    expect(scripts[0].incomplete).toEqual([]);
  });

  it("returns nothing when the API sent no code at all", () => {
    // A session recorded before code export existed. Nothing is broken; there
    // is simply nothing to offer.
    expect(toCodeScripts(undefined)).toEqual([]);
    expect(toCodeScripts(null)).toEqual([]);
    expect(toCodeScripts({})).toEqual([]);
  });

  it("skips a language whose renderer produced nothing", () => {
    expect(toCodeScripts({ python: "print(1)", r: "" }).map((s) => s.language)).toEqual(["python"]);
  });
});

describe("AnalysisCodeExport", () => {
  it("renders nothing for a session with no exported code", () => {
    const { container } = render(<AnalysisCodeExport scripts={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the first language's script by default", () => {
    render(<AnalysisCodeExport scripts={toCodeScripts(RAW_CODE)} />);

    expect(screen.getByRole("button", { name: "Python" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText(/import pandas as pd/)).toBeInTheDocument();
    expect(screen.queryByText(/library\(dplyr\)/)).not.toBeInTheDocument();
  });

  it("switches languages", async () => {
    const user = userEvent.setup();
    render(<AnalysisCodeExport scripts={toCodeScripts(RAW_CODE)} />);

    await user.click(screen.getByRole("button", { name: "R" }));
    expect(screen.getByText(/library\(dplyr\)/)).toBeInTheDocument();
    expect(screen.queryByText(/import pandas as pd/)).not.toBeInTheDocument();
  });

  it("copies the selected script", async () => {
    const user = userEvent.setup();
    const writeText = stubClipboard();
    render(<AnalysisCodeExport scripts={toCodeScripts(RAW_CODE)} />);

    await user.click(screen.getByRole("button", { name: /copy python script/i }));
    expect(writeText).toHaveBeenCalledWith(RAW_CODE.python);
    expect(screen.getByText("Copied")).toBeInTheDocument();
  });

  it("says which operations an export cannot reproduce", async () => {
    // A script that looks like a complete reproduction and silently omits a
    // step is worse than no script at all.
    const user = userEvent.setup();
    render(<AnalysisCodeExport scripts={toCodeScripts(RAW_CODE)} />);

    expect(screen.queryByText(/cannot reproduce/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "R" }));
    expect(screen.getByText(/cannot reproduce quantile_regression/)).toBeInTheDocument();
  });

  it("stays usable when the clipboard is denied", async () => {
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", {
      value: { writeText: vi.fn().mockRejectedValue(new Error("denied")) },
      configurable: true,
    });
    render(<AnalysisCodeExport scripts={toCodeScripts(RAW_CODE)} />);

    await user.click(screen.getByRole("button", { name: /copy python script/i }));
    expect(screen.getByText("Copy code")).toBeInTheDocument();
    expect(screen.getByText(/import pandas as pd/)).toBeInTheDocument();
  });
});
