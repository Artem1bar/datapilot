import { useLocation } from "react-router-dom";
import { Sun, Moon } from "lucide-react";
import { useAppStore } from "@/stores/app-store";
import { Button } from "@/components/ui/button";

const breadcrumbMap: Record<string, string> = {
  "/app/dashboard": "Datasets",
  "/app/upload": "Upload",
  "/app/settings": "Settings",
};

function getBreadcrumb(pathname: string): string {
  const exact = breadcrumbMap[pathname];
  if (exact) return exact;
  if (pathname.startsWith("/app/clean/")) return "Clean";
  if (pathname.startsWith("/app/analyze/")) return "Analyze";
  if (pathname.startsWith("/app/export/")) return "Export";
  return "App";
}

export function Topbar() {
  const location = useLocation();
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);

  const crumb = getBreadcrumb(location.pathname);

  const toggleTheme = () => {
    if (theme === "dark") {
      setTheme("light");
      document.documentElement.classList.remove("dark");
    } else {
      setTheme("dark");
      document.documentElement.classList.add("dark");
    }
  };

  return (
    <header className="flex h-12 items-center justify-between border-b border-[var(--line)] bg-[var(--surface-canvas)] px-4">
      <span className="text-[13px] font-medium text-ink">{crumb}</span>
      <Button
        variant="ghost"
        size="icon"
        onClick={toggleTheme}
        className="h-8 w-8 text-ink-tertiary hover:text-ink"
      >
        {theme === "dark" ? (
          <Sun className="h-4 w-4" />
        ) : (
          <Moon className="h-4 w-4" />
        )}
      </Button>
    </header>
  );
}
