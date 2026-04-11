import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { Sun, Moon, Monitor } from "lucide-react";
import { useAppStore } from "@/stores/app-store";
import { cn } from "@/lib/utils";

type ThemeOption = "light" | "dark" | "system";

const themeOptions: { value: ThemeOption; label: string; icon: typeof Sun }[] = [
  { value: "light", label: "Light", icon: Sun },
  { value: "dark", label: "Dark", icon: Moon },
  { value: "system", label: "System", icon: Monitor },
];

export default function Settings() {
  const theme = useAppStore((s) => s.theme);
  const setTheme = useAppStore((s) => s.setTheme);

  const handleTheme = (value: ThemeOption) => {
    if (value === "system") {
      const prefersDark = window.matchMedia("(prefers-color-scheme: dark)").matches;
      setTheme(prefersDark ? "dark" : "light");
    } else {
      setTheme(value);
    }
    if (value === "dark" || (value === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)) {
      document.documentElement.classList.add("dark");
    } else {
      document.documentElement.classList.remove("dark");
    }
  };

  return (
    <div className="mx-auto max-w-3xl p-6 md:p-8">
      <h1 className="text-xl font-semibold text-ink">Settings</h1>
      <p className="mt-0.5 text-[13px] text-ink-tertiary">
        Customize your experience.
      </p>

      <Tabs defaultValue="appearance" className="mt-6">
        <TabsList>
          <TabsTrigger value="appearance">Appearance</TabsTrigger>
          <TabsTrigger value="about">About</TabsTrigger>
        </TabsList>

        <TabsContent value="appearance" className="mt-5">
          <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-primary)] p-5">
            <h3 className="text-sm font-medium text-ink">Theme</h3>
            <div className="mt-4 flex gap-2">
              {themeOptions.map(({ value, label, icon: Icon }) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => handleTheme(value)}
                  className={cn(
                    "flex flex-1 flex-col items-center gap-2 rounded-lg border p-3.5 text-[13px] font-medium transition-all",
                    theme === value
                      ? "border-brand-500 bg-brand-50 text-brand-700"
                      : "border-[var(--line)] text-ink-secondary hover:border-[var(--line-strong)]",
                  )}
                >
                  <Icon className="h-4.5 w-4.5" />
                  {label}
                </button>
              ))}
            </div>
          </div>
        </TabsContent>

        <TabsContent value="about" className="mt-5">
          <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-primary)] p-5">
            <div className="flex items-center gap-3">
              <span className="text-[15px] font-bold tracking-tight text-brand-600">DataPilot</span>
              <Badge variant="secondary" className="bg-brand-50 text-brand-600 text-[11px] font-medium">v0.1.0</Badge>
            </div>
            <div className="my-4 h-px bg-[var(--line)]" />
            <p className="text-[13px] leading-relaxed text-ink-secondary">
              AI-powered data cleaning, analysis, and export. Upload messy spreadsheets and get clean data, smart insights, and polished exports.
            </p>
            <div className="mt-3 space-y-1 text-xs text-ink-muted">
              <p>React &middot; FastAPI &middot; Claude AI</p>
              <p>PostgreSQL &middot; Redis &middot; MinIO</p>
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
