import { useEffect, useState } from "react";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Button } from "@/components/ui/button";
import { getSettings, updateSettings, type UserPreferences } from "@/lib/settings-api";

interface FieldProps {
  label: string;
  description?: string;
  children: React.ReactNode;
}

function Field({ label, description, children }: FieldProps) {
  return (
    <div className="flex items-start justify-between gap-6 border-b border-[var(--line)] py-4 last:border-0">
      <div className="min-w-0 flex-1">
        <Label className="text-[13px] font-medium text-ink">{label}</Label>
        {description && <p className="mt-0.5 text-[12px] text-ink-muted">{description}</p>}
      </div>
      <div className="w-56 shrink-0">{children}</div>
    </div>
  );
}

function Choice<T extends string>({
  value,
  onChange,
  options,
}: {
  value: T;
  onChange: (v: T) => void;
  options: { value: T; label: string }[];
}) {
  return (
    <Select value={value} onValueChange={(v) => onChange(v as T)}>
      <SelectTrigger>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((o) => (
          <SelectItem key={o.value} value={o.value}>
            {o.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

export function CleaningSettings() {
  const [prefs, setPrefs] = useState<UserPreferences | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    getSettings()
      .then((p) => active && setPrefs(p))
      .catch((e) => active && setLoadError(e instanceof Error ? e.message : "Failed to load settings"));
    return () => {
      active = false;
    };
  }, []);

  function set<K extends keyof UserPreferences>(key: K, value: UserPreferences[K]) {
    setPrefs((p) => (p ? { ...p, [key]: value } : p));
    setSaved(false);
  }

  async function handleSave() {
    if (!prefs) return;
    setSaving(true);
    setSaveError(null);
    try {
      const updated = await updateSettings(prefs);
      setPrefs(updated);
      setSaved(true);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  if (loadError) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50/50 p-5 text-[13px] text-amber-700">
        {loadError}
      </div>
    );
  }

  if (!prefs) {
    return <div className="p-5 text-[13px] text-ink-muted">Loading settings…</div>;
  }

  return (
    <div className="rounded-lg border border-[var(--line)] bg-[var(--surface-primary)] p-5">
      <Field
        label="Cleaning aggressiveness"
        description="How assertively the AI cleans borderline data."
      >
        <Choice
          value={prefs.cleaning_aggressiveness}
          onChange={(v) => set("cleaning_aggressiveness", v)}
          options={[
            { value: "conservative", label: "Conservative" },
            { value: "standard", label: "Standard" },
            { value: "aggressive", label: "Aggressive" },
          ]}
        />
      </Field>

      <Field label="Domain" description="Enable survey-specific heuristics, or keep it generic.">
        <Choice
          value={prefs.domain}
          onChange={(v) => set("domain", v)}
          options={[
            { value: "auto", label: "Auto-detect" },
            { value: "survey", label: "Survey" },
            { value: "generic", label: "Generic" },
          ]}
        />
      </Field>

      <Field label="Cap strategy" description="How outlier ceilings are chosen from the data.">
        <Choice
          value={prefs.cap_strategy}
          onChange={(v) => set("cap_strategy", v)}
          options={[
            { value: "off", label: "Off" },
            { value: "auto", label: "Auto (from stats)" },
            { value: "manual", label: "Manual" },
          ]}
        />
      </Field>

      <Field label="Outlier method">
        <Choice
          value={prefs.outlier_method}
          onChange={(v) => set("outlier_method", v)}
          options={[
            { value: "mad", label: "MAD (robust)" },
            { value: "iqr", label: "IQR" },
            { value: "none", label: "None" },
          ]}
        />
      </Field>

      <Field label="Outlier threshold" description="Higher = more forgiving.">
        <Input
          type="number"
          step="0.1"
          min={0}
          max={100}
          value={prefs.outlier_threshold}
          onChange={(e) => set("outlier_threshold", Number(e.target.value))}
        />
      </Field>

      <Field label="Review plans before applying" description="Off = auto-apply generated plans.">
        <div className="flex justify-end">
          <Switch checked={prefs.review_first} onCheckedChange={(v) => set("review_first", v)} />
        </div>
      </Field>

      <Field label="Deduplicate by default">
        <div className="flex justify-end">
          <Switch checked={prefs.dedup_default} onCheckedChange={(v) => set("dedup_default", v)} />
        </div>
      </Field>

      <Field label="Max remediation rounds" description="How many AI fix-up passes after cleaning.">
        <Input
          type="number"
          min={0}
          max={5}
          value={prefs.max_remediation_rounds}
          onChange={(e) => set("max_remediation_rounds", Number(e.target.value))}
        />
      </Field>

      <Field label="AI sample size" description="Rows sent to the model when planning.">
        <Input
          type="number"
          min={10}
          max={2000}
          value={prefs.ai_sample_size}
          onChange={(e) => set("ai_sample_size", Number(e.target.value))}
        />
      </Field>

      <Field label="Standing instructions" description="Applied to every cleaning plan.">
        <Textarea
          rows={3}
          value={prefs.custom_instructions}
          placeholder="e.g. Always keep the raw email column."
          onChange={(e) => set("custom_instructions", e.target.value)}
        />
      </Field>

      <div className="mt-5 flex items-center justify-end gap-3">
        {saveError && <span className="text-[12px] text-red-600">{saveError}</span>}
        {saved && !saveError && <span className="text-[12px] text-teal-600">Saved</span>}
        <Button
          size="sm"
          onClick={handleSave}
          disabled={saving}
          className="bg-brand-600 text-white hover:bg-brand-700"
        >
          {saving ? "Saving…" : "Save changes"}
        </Button>
      </div>
    </div>
  );
}
