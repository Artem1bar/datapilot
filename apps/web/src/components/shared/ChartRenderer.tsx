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
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from "recharts";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { ChartConfig } from "@/types";

interface ChartRendererProps {
  config: ChartConfig;
  data: Record<string, unknown>[];
}

/** LSU brand palette — purple-dominant with gold accents */
const LSU_COLORS = [
  "#461D7C", // LSU purple
  "#FDD023", // LSU gold
  "#6B32A8", // lighter purple
  "#E8B820", // deeper gold
  "#8B5CF6", // violet
  "#F59E0B", // amber
  "#7C3AED", // indigo-purple
  "#D97706", // warm orange
];

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

  const renderChart = () => {
    switch (config.chart_type) {
      case "bar":
      case "histogram":
        return (
          <BarChart data={data} barCategoryGap="30%">
            <CartesianGrid {...gridProps} />
            <XAxis dataKey={xKey} {...axisProps} />
            <YAxis {...axisProps} />
            <Tooltip
              contentStyle={{
                background: "var(--surface-primary)",
                border: "1px solid var(--line)",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
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
            <Tooltip
              contentStyle={{
                background: "var(--surface-primary)",
                border: "1px solid var(--line)",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
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
                <Cell key={i} fill={LSU_COLORS[i % LSU_COLORS.length]} />
              ))}
            </Pie>
            <Tooltip
              contentStyle={{
                background: "var(--surface-primary)",
                border: "1px solid var(--line)",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Legend iconSize={10} wrapperStyle={{ fontSize: 12 }} />
          </PieChart>
        );

      case "scatter":
        return (
          <ScatterChart>
            <CartesianGrid {...gridProps} />
            <XAxis dataKey={xKey} {...axisProps} name={config.x_field} />
            <YAxis dataKey={yKey} {...axisProps} name={config.y_field} />
            <Tooltip
              cursor={{ strokeDasharray: "3 3" }}
              contentStyle={{
                background: "var(--surface-primary)",
                border: "1px solid var(--line)",
                borderRadius: 8,
                fontSize: 12,
              }}
            />
            <Scatter data={data} fill="#461D7C" opacity={0.75} />
          </ScatterChart>
        );

      default:
        return (
          <div className="flex h-full items-center justify-center text-sm text-ink-muted">
            Chart type "{config.chart_type}" is not supported yet.
          </div>
        );
    }
  };

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
      <div ref={containerRef} className="h-[240px] w-full">
        <ResponsiveContainer width="100%" height="100%">
          {renderChart()}
        </ResponsiveContainer>
      </div>
    </div>
  );
}
