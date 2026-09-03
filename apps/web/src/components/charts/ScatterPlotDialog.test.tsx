import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ScatterPlotDialog } from "./ScatterPlotDialog";
import type { ScatterColumns } from "@/lib/scatter";

const columns: ScatterColumns = {
  numeric: [
    { name: "units", dtype: "int64", uniqueCount: 40 },
    { name: "revenue", dtype: "float64", uniqueCount: 50 },
    { name: "cost", dtype: "float64", uniqueCount: 50 },
  ],
  categorical: [{ name: "region", dtype: "object", uniqueCount: 3 }],
};

function renderDialog(
  overrides: Partial<React.ComponentProps<typeof ScatterPlotDialog>> = {},
) {
  const onSubmit = vi.fn();
  render(
    <ScatterPlotDialog
      open
      onOpenChange={() => {}}
      columns={columns}
      onSubmit={onSubmit}
      {...overrides}
    />,
  );
  return { onSubmit };
}

describe("ScatterPlotDialog", () => {
  it("preselects the first two numeric columns and plots them", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog();

    expect(screen.getByLabelText("X axis")).toHaveValue("units");
    expect(screen.getByLabelText("Y axis")).toHaveValue("revenue");

    await user.click(screen.getByRole("button", { name: "Plot" }));
    expect(onSubmit).toHaveBeenCalledWith({
      x: "units",
      y: "revenue",
      colorBy: null,
      size: null,
    });
  });

  it("keeps the two axes distinct", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog();

    // Choosing the current y as the new x empties y rather than plotting a
    // column against itself.
    await user.selectOptions(screen.getByLabelText("X axis"), "revenue");
    expect(screen.getByLabelText("Y axis")).toHaveValue("");
    expect(screen.getByRole("button", { name: "Plot" })).toBeDisabled();

    const yOptions = Array.from(
      screen.getByLabelText("Y axis").querySelectorAll("option"),
    ).map((o) => o.value);
    expect(yOptions).not.toContain("revenue");

    await user.selectOptions(screen.getByLabelText("Y axis"), "cost");
    await user.click(screen.getByRole("button", { name: "Plot" }));
    expect(onSubmit).toHaveBeenCalledWith({
      x: "revenue",
      y: "cost",
      colorBy: null,
      size: null,
    });
  });

  it("offers the color columns and sends the chosen one", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog();

    await user.selectOptions(screen.getByLabelText("Color by"), "region");
    await user.click(screen.getByRole("button", { name: "Plot" }));
    expect(onSubmit).toHaveBeenCalledWith({
      x: "units",
      y: "revenue",
      colorBy: "region",
      size: null,
    });
  });

  it("offers a bubble size from the remaining numeric columns", async () => {
    const user = userEvent.setup();
    const { onSubmit } = renderDialog();

    const sizeOptions = Array.from(
      screen.getByLabelText("Bubble size").querySelectorAll("option"),
    ).map((o) => o.value);
    expect(sizeOptions).toEqual(["", "cost"]);

    await user.selectOptions(screen.getByLabelText("Bubble size"), "cost");
    await user.click(screen.getByRole("button", { name: "Plot" }));
    expect(onSubmit).toHaveBeenCalledWith({
      x: "units",
      y: "revenue",
      colorBy: null,
      size: "cost",
    });
  });

  it("shows the loading state while the columns arrive", () => {
    renderDialog({ columns: null });
    expect(screen.getByText(/loading columns/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Plot" })).toBeNull();
  });

  it("explains when the dataset cannot be plotted", () => {
    renderDialog({
      columns: { numeric: [columns.numeric[0]], categorical: [] },
    });
    expect(
      screen.getByText(/at least two numeric columns/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Plot" })).toBeDisabled();
  });

  it("surfaces load and plot errors", () => {
    renderDialog({ columns: null, loadError: "Attach a dataset first." });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Attach a dataset first.",
    );
  });

  it("shows the API's problems beside the form", () => {
    renderDialog({ error: "column 'x' is not numeric" });
    expect(screen.getByRole("alert")).toHaveTextContent("is not numeric");
    expect(screen.getByRole("button", { name: "Plot" })).toBeEnabled();
  });

  it("disables the form while a plot is in flight", () => {
    renderDialog({ submitting: true });
    expect(screen.getByRole("button", { name: /plotting/i })).toBeDisabled();
  });
});
