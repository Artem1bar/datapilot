import { MessageCircleQuestion } from "lucide-react";
import type { ScatterInterpretation } from "@/lib/scatter";

/**
 * What the plot says, what it does not, and what to ask next.
 *
 * The sentences are computed by the API from the fitted statistics; nothing
 * here is written by a model. The next steps are questions the chat can
 * answer, so a reader who wants to go further does not have to know which
 * test to ask for.
 */
interface Props {
  reading: ScatterInterpretation;
  onAsk?: (question: string) => void;
}

export function PlotReading({ reading, onAsk }: Props) {
  return (
    <section className="mt-3 space-y-3 border-t border-[var(--line)] pt-3">
      <div className="space-y-1.5">
        <h4 className="text-[12px] font-semibold uppercase tracking-wide text-ink-muted">
          Reading this plot
        </h4>
        {reading.summary.map((sentence) => (
          <p key={sentence} className="text-[13px] leading-relaxed text-ink">
            {sentence}
          </p>
        ))}
      </div>

      {reading.caveats.length > 0 ? (
        <div className="space-y-1">
          <h4 className="text-[12px] font-semibold uppercase tracking-wide text-ink-muted">
            Keep in mind
          </h4>
          <ul className="list-disc space-y-1 pl-4 text-[12px] leading-relaxed text-ink-secondary">
            {reading.caveats.map((caveat) => (
              <li key={caveat}>{caveat}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {reading.nextSteps.length > 0 ? (
        <div className="space-y-1.5">
          <h4 className="text-[12px] font-semibold uppercase tracking-wide text-ink-muted">
            Ask next
          </h4>
          <div className="flex flex-col gap-1.5">
            {reading.nextSteps.map((step) => (
              <button
                key={step.question}
                type="button"
                onClick={() => onAsk?.(step.question)}
                className="flex items-start gap-2 rounded-lg border border-[var(--line)] bg-[var(--surface-canvas)] px-3 py-2 text-left transition-colors hover:border-brand-300 hover:bg-brand-50"
              >
                <MessageCircleQuestion
                  className="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-500"
                  aria-hidden
                />
                <span className="flex flex-col">
                  <span className="text-[12px] font-medium text-ink">{step.question}</span>
                  <span className="text-[11px] text-ink-muted">{step.why}</span>
                </span>
              </button>
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
