import { NavLink, useParams, useLocation } from "react-router-dom";
import {
  LayoutDashboard,
  Upload,
  Settings,
  PanelLeftClose,
  PanelLeft,
  Sparkles,
  MessageSquare,
  Download,
} from "lucide-react";
import { useAppStore } from "@/stores/app-store";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";

/* ── Nav items ───────────────────────────────────────────────────────────── */

const mainNav = [
  { to: "/app/dashboard", label: "Datasets", icon: LayoutDashboard },
  { to: "/app/upload", label: "Upload", icon: Upload },
] as const;

const bottomNav = [
  { to: "/app/settings", label: "Settings", icon: Settings },
] as const;

/* ── Dataset actions ─────────────────────────────────────────────────────── */

function useActiveDatasetId(): string | null {
  const params = useParams<{ datasetId: string }>();
  const location = useLocation();

  if (params.datasetId) return params.datasetId;

  const match = location.pathname.match(
    /\/app\/(?:clean|analyze|export)\/([a-f0-9-]+)/,
  );
  return match?.[1] ?? null;
}

/* ── Component ───────────────────────────────────────────────────────────── */

export function Sidebar() {
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);
  const activeDatasetId = useActiveDatasetId();

  const datasetNav = activeDatasetId
    ? [
        { to: `/app/clean/${activeDatasetId}`, label: "Clean", icon: Sparkles },
        { to: `/app/analyze/${activeDatasetId}`, label: "Analyze", icon: MessageSquare },
        { to: `/app/export/${activeDatasetId}`, label: "Export", icon: Download },
      ]
    : [];

  return (
    <TooltipProvider delayDuration={0}>
      <aside
        className={cn(
          "flex h-screen flex-col border-r border-[var(--line)] bg-[var(--surface-canvas)] transition-all duration-200",
          sidebarOpen ? "w-[220px]" : "w-16",
        )}
      >
        {/* Logo & toggle */}
        <div className="flex h-14 items-center justify-between border-b border-[var(--line)] px-3">
          {sidebarOpen && (
            <span className="text-[15px] font-bold tracking-tight text-brand-600">
              Data<span className="text-gold-500">Pilot</span>
            </span>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={toggleSidebar}
            className="h-8 w-8 shrink-0 text-ink-tertiary hover:text-ink transition-all duration-150 hover:bg-[var(--surface-inset)] active:scale-90"
          >
            {sidebarOpen ? (
              <PanelLeftClose className="h-4 w-4" />
            ) : (
              <PanelLeft className="h-4 w-4" />
            )}
          </Button>
        </div>

        {/* Main nav */}
        <nav className="flex-1 space-y-0.5 px-2 py-3">
          {mainNav.map((item) => (
            <SidebarLink key={item.to} {...item} sidebarOpen={sidebarOpen} />
          ))}

          {datasetNav.length > 0 && (
            <>
              <div className="my-3 h-px bg-[var(--line)]" />
              {sidebarOpen && (
                <p className="mb-1.5 px-3 text-[10px] font-semibold uppercase tracking-widest text-ink-muted">
                  Dataset
                </p>
              )}
              {datasetNav.map((item) => (
                <SidebarLink key={item.to} {...item} sidebarOpen={sidebarOpen} />
              ))}
            </>
          )}
        </nav>

        {/* Bottom */}
        <div className="border-t border-[var(--line)] px-2 py-3">
          {bottomNav.map((item) => (
            <SidebarLink key={item.to} {...item} sidebarOpen={sidebarOpen} />
          ))}
        </div>
      </aside>
    </TooltipProvider>
  );
}

/* ── Nav link ────────────────────────────────────────────────────────────── */

function SidebarLink({
  to,
  label,
  icon: Icon,
  sidebarOpen,
}: {
  to: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  sidebarOpen: boolean;
}) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <NavLink
          to={to}
          className={({ isActive }) =>
            cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium transition-all duration-150",
              isActive
                ? "bg-brand-100 text-brand-600 shadow-[inset_0_0_0_1px_var(--brand-300)]"
                : "text-ink-secondary hover:bg-[var(--surface-inset)] hover:text-ink hover:shadow-[inset_0_0_0_1px_var(--line-strong)]",
              !sidebarOpen && "justify-center px-0",
            )
          }
        >
          <Icon className="h-[18px] w-[18px] shrink-0 transition-transform duration-150 group-hover:scale-110" />
          {sidebarOpen && <span>{label}</span>}
        </NavLink>
      </TooltipTrigger>
      {!sidebarOpen && (
        <TooltipContent side="right">{label}</TooltipContent>
      )}
    </Tooltip>
  );
}
