import { NavLink, useNavigate } from "react-router-dom";
import {
  PanelLeftClose,
  PanelLeft,
  Plus,
  Database,
  Settings,
} from "lucide-react";
import { AnimatePresence, motion } from "framer-motion";
import logoSrc from "@/assets/datatiger-logo.svg";
import { useAppStore } from "@/stores/app-store";
import { useSessionStore } from "@/stores/session-store";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { SessionItem } from "./SessionItem";

/* ── Bottom nav items ───────────────────────────────────────────────────── */

const bottomNav = [
  { to: "/app/cleaned-datasets", label: "Cleaned datasets", icon: Database },
  { to: "/app/settings", label: "Settings", icon: Settings },
] as const;

/* ── Component ──────────────────────────────────────────────────────────── */

export function SessionSidebar() {
  const navigate = useNavigate();
  const sidebarOpen = useAppStore((s) => s.sidebarOpen);
  const toggleSidebar = useAppStore((s) => s.toggleSidebar);

  const sessions = useSessionStore((s) => s.sessions);
  const activeSessionId = useSessionStore((s) => s.activeSessionId);
  const createSession = useSessionStore((s) => s.createSession);
  const setActiveSession = useSessionStore((s) => s.setActiveSession);
  const renameSession = useSessionStore((s) => s.renameSession);
  const pinSession = useSessionStore((s) => s.pinSession);
  const deleteSession = useSessionStore((s) => s.deleteSession);

  const handleSessionClick = (id: string) => {
    setActiveSession(id);
    navigate("/app");
  };

  const handleNewSession = () => {
    createSession();
    navigate("/app");
  };

  const pinnedSessions = sessions.filter((s) => s.pinned);
  const recentSessions = sessions.filter((s) => !s.pinned);

  return (
    <TooltipProvider delayDuration={0}>
      <motion.aside
        animate={{ width: sidebarOpen ? 260 : 64 }}
        transition={{ type: "spring", stiffness: 300, damping: 30 }}
        className="flex h-screen flex-col border-r border-[var(--line)] bg-[var(--surface-canvas)] overflow-hidden"
      >
        {/* ── Header ───────────────────────────────────────────── */}
        <div className="flex h-14 items-center justify-between border-b border-[var(--line)] px-3">
          <AnimatePresence>
            {sidebarOpen && (
              <motion.button
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.15 }}
                type="button"
                onClick={() => navigate("/app")}
                className="flex items-center gap-2 min-w-0 hover:opacity-80 transition-opacity"
              >
                <img src={logoSrc} alt="Data Tiger" className="h-8 w-auto object-contain max-w-[160px]" />
              </motion.button>
            )}
          </AnimatePresence>
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

        {/* ── New session button ────────────────────────────────── */}
        <div className="px-2 pt-3 pb-1">
          {sidebarOpen ? (
            <Button
              className="w-full bg-brand-600 text-white hover:bg-brand-700 transition-all duration-150 hover:shadow-md active:scale-[0.98]"
              size="sm"
              onClick={handleNewSession}
            >
              <Plus className="mr-1.5 h-3.5 w-3.5" />
              New session
            </Button>
          ) : (
            <Tooltip>
              <TooltipTrigger asChild>
                <Button
                  variant="ghost"
                  size="icon"
                  className="mx-auto flex h-9 w-9 items-center justify-center text-brand-600 hover:bg-brand-50"
                  onClick={handleNewSession}
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </TooltipTrigger>
              <TooltipContent side="right">New session</TooltipContent>
            </Tooltip>
          )}
        </div>

        {/* ── Session list ──────────────────────────────────────── */}
        <nav className="flex-1 overflow-y-auto px-2 py-2 space-y-0.5">
          {/* Pinned */}
          {pinnedSessions.length > 0 && (
            <>
              <AnimatePresence>
                {sidebarOpen && (
                  <motion.p
                    initial={{ opacity: 0 }}
                    animate={{ opacity: 1 }}
                    exit={{ opacity: 0 }}
                    className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-ink-muted"
                  >
                    Pinned
                  </motion.p>
                )}
              </AnimatePresence>
              {pinnedSessions.map((session) => (
                <SessionItem
                  key={session.id}
                  session={session}
                  isActive={session.id === activeSessionId}
                  sidebarOpen={sidebarOpen}
                  onClick={() => handleSessionClick(session.id)}
                  onRename={(title) => renameSession(session.id, title)}
                  onPin={() => pinSession(session.id)}
                  onDelete={() => deleteSession(session.id)}
                />
              ))}
              {sidebarOpen && <div className="my-2 h-px bg-[var(--line)]" />}
            </>
          )}

          {/* Recent */}
          <AnimatePresence>
            {sidebarOpen && recentSessions.length > 0 && (
              <motion.p
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="mb-1 px-3 text-[10px] font-semibold uppercase tracking-widest text-ink-muted"
              >
                Recent
              </motion.p>
            )}
          </AnimatePresence>
          {recentSessions.map((session) => (
            <SessionItem
              key={session.id}
              session={session}
              isActive={session.id === activeSessionId}
              sidebarOpen={sidebarOpen}
              onClick={() => handleSessionClick(session.id)}
              onRename={(title) => renameSession(session.id, title)}
              onPin={() => pinSession(session.id)}
              onDelete={() => deleteSession(session.id)}
            />
          ))}

          {sessions.length === 0 && sidebarOpen && (
            <p className="px-3 py-6 text-center text-[12px] text-ink-muted">
              No sessions yet. Click &ldquo;New session&rdquo; to start.
            </p>
          )}
        </nav>

        {/* ── Bottom nav ───────────────────────────────────────── */}
        <div className="border-t border-[var(--line)] px-2 py-3 space-y-0.5">
          {bottomNav.map(({ to, label, icon: Icon }) => (
            <Tooltip key={to}>
              <TooltipTrigger asChild>
                <NavLink
                  to={to}
                  className={({ isActive }) =>
                    cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium transition-all duration-150",
                      isActive
                        ? "bg-brand-100 text-brand-600 shadow-[inset_0_0_0_1px_var(--brand-300)]"
                        : "text-ink-secondary hover:bg-[var(--surface-inset)] hover:text-ink",
                      !sidebarOpen && "justify-center px-0",
                    )
                  }
                >
                  <Icon className="h-[18px] w-[18px] shrink-0" />
                  <AnimatePresence>
                    {sidebarOpen && (
                      <motion.span
                        initial={{ opacity: 0 }}
                        animate={{ opacity: 1 }}
                        exit={{ opacity: 0 }}
                        transition={{ duration: 0.15 }}
                      >
                        {label}
                      </motion.span>
                    )}
                  </AnimatePresence>
                </NavLink>
              </TooltipTrigger>
              {!sidebarOpen && (
                <TooltipContent side="right">{label}</TooltipContent>
              )}
            </Tooltip>
          ))}
        </div>
      </motion.aside>
    </TooltipProvider>
  );
}
