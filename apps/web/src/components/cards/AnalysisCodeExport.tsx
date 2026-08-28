import { useState } from "react";
import { Check, Copy, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { AnalysisCodeScript } from "@/types";

/**
 * The executed analysis as a script the reader can run themselves.
 *
 * This is the trust bridge. Every other honesty measure in the product — the
 * methods note, the assumption checks, the provenance record — is the product
 * describing its own work. A script a researcher runs in their own environment
 * is the one artefact that can contradict it, which is exactly what makes it
 * worth shipping.
 *
 * An export that cannot express one of the executed operations says so. A
 * script that looks like a complete reproduction and silently omits a step is
 * worse than no script at all.
 */

interface Props {
  scripts: readonly AnalysisCodeScript[];
}

export function AnalysisCodeExport({ scripts }: Props) {
  const [language, setLanguage] = useState(scripts[0]?.language);
  const [copied, setCopied] = useState(false);

  // A session recorded before code export existed carries no scripts. Nothing
  // is broken; there is simply nothing to offer, so nothing is rendered.
  if (scripts.length === 0) return null;

  const active =
    scripts.find((script) => script.language === language) ?? scripts[0];

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(active.source);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard access can be denied; the script stays selectable on screen.
      setCopied(false);
    }
  };

  return (
    <div className="border-t border-[var(--line)] px-4 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div
          className="flex items-center gap-1"
          role="group"
          aria-label="Export language"
        >
          {scripts.map((script) => {
            const selected = script.language === active.language;
            return (
              <button
                key={script.language}
                type="button"
                aria-pressed={selected}
                onClick={() => {
                  setLanguage(script.language);
                  setCopied(false);
                }}
                className={`rounded-md border px-2.5 py-1 text-[12px] transition-colors duration-100 ${
                  selected
                    ? "border-brand-500 bg-[var(--surface-raised)] font-medium text-ink"
                    : "border-[var(--line)] text-ink-muted hover:bg-[var(--surface-raised)]"
                }`}
              >
                {script.label}
              </button>
            );
          })}
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={copy}
          className="h-7 gap-1.5 text-[12px]"
          aria-label={`Copy ${active.label} script`}
        >
          {copied ? (
            <Check className="h-3 w-3" />
          ) : (
            <Copy className="h-3 w-3" />
          )}
          {copied ? "Copied" : "Copy code"}
        </Button>
      </div>

      {active.incomplete.length > 0 ? (
        <p className="mt-2 flex items-start gap-1.5 text-[11px] leading-relaxed text-amber-800">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            This {active.label} export cannot reproduce{" "}
            {active.incomplete.join(", ")}. Running it will not give you every
            figure in the answer.
          </span>
        </p>
      ) : null}

      <pre className="mt-2 max-h-72 overflow-auto rounded-lg border border-[var(--line)] bg-[var(--surface-raised)] p-3 text-[11px] leading-relaxed">
        <code>{active.source}</code>
      </pre>
    </div>
  );
}
