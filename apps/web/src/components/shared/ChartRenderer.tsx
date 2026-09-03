import { useRef, useCallback } from "react";
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  LineChart,
  Line,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import { ScatterPlot } from "@/components/charts/ScatterPlot";
import { CHART_COLORS } from "@/components/charts/palette";
import type { ChartConfig } from "@/types";

interface ChartRendererProps {
  config: ChartConfig;
  data: Record<string, unknown>[];
}

/**
 * Detect whether Claude-generated data uses {x, y} generic keys
 * vs field-name keys matching config.x_field / config.y_field.
 */
function resolveKeys(
  config: ChartConfig,
  data: Record<string, unknown>[],
): { xKey: string; yKey: string } {
  if (data.length > 0 && "x" in data[0] && "y" in data[0]) {
    return { xKey: "x", yKey: "y" };
  }
  return {
    xKey: config.x_field ?? "x",
    yKey: config.y_field ?? "y",
  };
}

export function ChartRenderer({ config, data }: ChartRendererProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const { xKey, yKey } = resolveKeys(config, data);

  const handleDownload = useCallback(() => {
    const svg = containerRef.current?.querySelector("svg");
    if (!svg) return;

    const canvas = document.createElement("canvas");
    const bbox = svg.getBoundingClientRect();
    canvas.width = bbox.width * 2;
    canvas.height = bbox.height * 2;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    ctx.scale(2, 2);
    const svgData = new XMLSerializer().serializeToString(svg);
    const img = new Image();
    img.onload = () => {
      ctx.fillStyle = "#ffffff";
      ctx.fillRect(0, 0, canvas.width, canvas.height);
      ctx.drawImage(img, 0, 0);
      const a = document.createElement("a");
      a.download = `${config.title || "chart"}.png`;
      a.href = canvas.toDataURL("image/png");
      a.click();
    };
    img.src = `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svgData)}`;
  }, [config.title]);

  const gridProps = {
    strokeDasharray: "3 3",
    stroke: "var(--line)",
    opacity: 0.6,
  };

  const axisProps = {
    fontSize: 11,
    tick: { fill: "var(--ink-muted, #9ca3af)" },
    axisLine: { stroke: "var(--line)" },
    tickLine: false,
  };

  const tooltipStyle = {
    background: "var(--surface-primary)",
    border: "1px solid var(--line)",
    borderRadius: 8,
    fontSize: 12,
  };

  const renderChart = () => {
    switch (config.chart_type) {
      case "bar":
      case "histogram":
        return (
          <BarChart data={data} barCategoryGap="30%">
            <CartesianGrid {...gridProps} />
            <XAxis dataKey={xKey} {...axisProps} />
            <YAxis {...axisProps} />
            <Tooltip contentStyle={tooltipStyle} />
            <Bar
              dataKey={yKey}
              fill="#461D7C"
              radius={[4, 4, 0, 0]}
              animationDuration={700}
              animationEasing="ease-out"
            >
              {data.map((_, i) => (
                <Cell
                  key={i}
                  fill={i % 2 === 0 ? "#461D7C" : "#6B32A8"}
                />
              ))}
            </Bar>
          </BarChart>
        );

      case "line":
        return (
          <LineChart data={data}>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey={xKey} {...axisProps} />
            <YAxis {...axisProps} />
            <Tooltip contentStyle={tooltipStyle} />
            <Line
              type="monotone"
              dataKey={yKey}
              stroke="#461D7C"
              strokeWidth={2.5}
              dot={{ r: 4, fill: "#461D7C", strokeWidth: 2, stroke: "#FDD023" }}
              activeDot={{ r: 5, fill: "#FDD023", stroke: "#461D7C", strokeWidth: 2 }}
              animationDuration={900}
              animationEasing="ease-out"
            />
          </LineChart>
        );

      case "pie":
        return (
          <PieChart>
            <Pie
              data={data}
              dataKey={yKey}
              nameKey={xKey}
              cx="50%"
              cy="50%"
              outerRadius={100}
              innerRadius={40}
              paddingAngle={2}
              animationDuration={900}
              animationEasing="ease-out"
            >
              {data.map((_, i) => (
                <Cell key={i} fill={CHART_COLORS[i % CHART_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} />
            <Legend iconSize={10} wrapperStyle={{ fontSize: 12 }} />
          </PieChart>
        );

      default:
        return (
          <div className="flex h-full items-center justify-center text-sm text-ink-muted">
            Chart type "{config.chart_type}" is not supported yet.
          </div>
        );
    }
  };

  // A scatter draws its own axes, legend and caption, and needs the height
  // for them; the other charts share one fixed-height container.
  const chart =
    config.chart_type === "scatter" || config.chart_type === "bubble" ? (
      <ScatterPlot config={config} />
    ) : (
      <div className="h-[240px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          {renderChart()}
        </ResponsiveContainer>
      </div>
    );

  return (
    <div className="space-y-3 animate-fade-in">
      {config.title && (
        <div className="flex items-center justify-between gap-2">
          <h3 className="text-[13px] font-semibold leading-tight text-ink">
            {config.title}
          </h3>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDownload}
            className="h-7 shrink-0 gap-1 px-2 text-[11px] text-ink-muted hover:text-ink"
          >
            <Download className="h-3 w-3" />
            PNG
          </Button>
        </div>
      )}
      <div ref={containerRef}>{chart}</div>
    </div>
  );
}
