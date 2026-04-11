import { useState } from "react";
import { motion } from "framer-motion";
import { BookOpen, ChevronDown, ChevronRight, Tag } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { staggerContainer, staggerItem } from "@/lib/motion";
import type { DataDictionaryPayload } from "@/types";

interface Props {
  payload: DataDictionaryPayload;
}

export function DataDictionaryCard({ payload }: Props) {
  const { datasetSummary, columns } = payload;
  const [expandedSet, setExpandedSet] = useState<ReadonlySet<string>>(new Set());

  const toggleExpanded = (name: string) => {
    setExpandedSet((prev) => {
      const next = new Set(prev);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  return (
    <div className="my-2 max-w-[85%]">
      <div className="rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] shadow-sm overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 border-b border-[var(--line)] bg-violet-50/50 px-4 py-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-violet-100 text-violet-600">
            <BookOpen className="h-4 w-4" />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-[13px] font-semibold text-ink">Data Dictionary</p>
            <p className="truncate text-[12px] text-ink-muted">{datasetSummary}</p>
          </div>
        </div>

        {/* Column list */}
        <motion.div
          variants={staggerContainer(0.03)}
          initial="hidden"
          animate="visible"
          className="divide-y divide-[var(--line)]"
        >
          {columns.map((col) => {
            const isExpanded = expandedSet.has(col.name);

            return (
              <motion.div key={col.name} variants={staggerItem}>
                {/* Collapsed row */}
                <button
                  type="button"
                  className="flex w-full items-center gap-3 px-4 py-2.5 text-left hover:bg-[var(--surface-raised)] transition-colors duration-100"
                  onClick={() => toggleExpanded(col.name)}
                >
                  {isExpanded ? (
                    <ChevronDown className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
                  ) : (
                    <ChevronRight className="h-3.5 w-3.5 shrink-0 text-ink-muted" />
                  )}
                  <span className="min-w-0 flex-1 truncate font-mono text-[13px] text-ink">
                    {col.name}
                  </span>
                  <Badge
                    variant="outline"
                    className="shrink-0 text-[10px] border-[var(--line)]"
                  >
                    {col.dataType}
                  </Badge>
                  <span className="hidden sm:inline shrink-0 truncate max-w-[200px] text-[12px] text-ink-muted">
                    {col.description}
                  </span>
                </button>

                {/* Expanded details */}
                {isExpanded && (
                  <div className="border-t border-[var(--line)] bg-[var(--surface-raised)] px-4 py-3 pl-10 space-y-2">
                    <div>
                      <p className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">
                        Description
                      </p>
                      <p className="text-[13px] text-ink">{col.description}</p>
                    </div>
                    <div>
                      <p className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">
                        Business Meaning
                      </p>
                      <p className="text-[13px] text-ink">{col.businessMeaning}</p>
                    </div>
                    {col.constraints.length > 0 && (
                      <div>
                        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">
                          Constraints
                        </p>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {col.constraints.map((constraint) => (
                            <Badge
                              key={constraint}
                              variant="outline"
                              className="text-[10px] border-violet-200 text-violet-700"
                            >
                              <Tag className="mr-1 h-2.5 w-2.5" />
                              {constraint}
                            </Badge>
                          ))}
                        </div>
                      </div>
                    )}
                    {col.notes && (
                      <div>
                        <p className="text-[11px] font-medium uppercase tracking-wide text-ink-muted">
                          Notes
                        </p>
                        <p className="text-[12px] text-ink-secondary">{col.notes}</p>
                      </div>
                    )}
                  </div>
                )}
              </motion.div>
            );
          })}
        </motion.div>
      </div>
    </div>
  );
}
