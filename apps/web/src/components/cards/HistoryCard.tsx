import { motion } from "framer-motion";
import { History, Clock, CheckCircle2, XCircle, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { HistoryPayload } from "@/types";

interface Props {
  payload: HistoryPayload;
}

const statusIcon: Record<string, React.ReactNode> = {
  completed: <CheckCircle2 className="h-3.5 w-3.5 text-teal-500" />,
  failed: <XCircle className="h-3.5 w-3.5 text-red-500" />,
  running: <Loader2 className="h-3.5 w-3.5 animate-spin text-blue-500" />,
  pending: <Clock className="h-3.5 w-3.5 text-ink-muted" />,
};

const typeBadgeColor: Record<string, string> = {
  clean: "border-teal-200 text-teal-700 bg-teal-50/50",
  inspect: "border-blue-200 text-blue-700 bg-blue-50/50",
  transform: "border-violet-200 text-violet-700 bg-violet-50/50",
  validate: "border-amber-200 text-amber-700 bg-amber-50/50",
};

function formatTimestamp(ts: string | null): string {
  if (!ts) return "";
  const date = new Date(ts);
  return date.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function HistoryCard({ payload }: Props) {
  const { filename, entries } = payload;

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[var(--line)] bg-slate-50/50 px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-slate-100 text-slate-600">
            <History className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">Operation History</p>
            <p className="truncate text-[12px] text-ink-muted">{filename}</p>
          </div>
        </div>

        {/* Timeline */}
        <motion.div
          variants={staggerContainer(0.04)}
          initial="hidden"
          animate="visible"
          className="relative px-4 py-3"
        >
          {/* Vertical line */}
          <div className="absolute left-[29px] top-3 bottom-3 w-px bg-[var(--line)]" />

          <div className="space-y-3">
            {entries.map((entry) => (
              <motion.div
                key={entry.id}
                variants={staggerItem}
                className="relative flex items-start gap-3 pl-5"
              >
                {/* Node dot */}
                <div className="absolute left-0 top-1 z-10 flex h-4 w-4 items-center justify-center rounded-full bg-[var(--surface-primary)] ring-2 ring-[var(--line)]">
                  {statusIcon[entry.status] ?? statusIcon.pending}
                </div>

                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Badge
                      variant="outline"
                      className={`text-[10px] ${typeBadgeColor[entry.type] ?? "border-[var(--line)] text-ink-muted"}`}
                    >
                      {entry.type}
                    </Badge>
                    <span className="text-[11px] text-ink-muted">
                      {formatTimestamp(entry.createdAt)}
                    </span>
                  </div>

                  {entry.summary && (
                    <div className="mt-1 flex gap-3 text-[11px] text-ink-secondary">
                      {entry.summary.rowsBefore != null && entry.summary.rowsAfter != null && (
                        <span>
                          {entry.summary.rowsBefore.toLocaleString()} &rarr;{" "}
                          {entry.summary.rowsAfter.toLocaleString()} rows
                        </span>
                      )}
                      {entry.summary.cellsModified != null && (
                        <span>{entry.summary.cellsModified.toLocaleString()} cells modified</span>
                      )}
                    </div>
                  )}

                  {entry.completedAt && (
                    <p className="mt-0.5 text-[10px] text-ink-muted">
                      Completed {formatTimestamp(entry.completedAt)}
                    </p>
                  )}
                </div>
              </motion.div>
            ))}
          </div>
        </motion.div>
      </div>
    </div>
  );
}
