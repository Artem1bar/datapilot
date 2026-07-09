import { Sparkles, BarChart3, FileText } from "lucide-react";
import { motion } from "framer-motion";
import tigerHeadSrc from "@/assets/tiger-head.svg";
import { staggerContainer, staggerItem, scaleIn, spring } from "@/lib/motion";

interface EmptyStateProps {
  onChipClick: (text: string) => void;
}

const actions = [
  { text: "Clean my dataset", icon: Sparkles, description: "Remove duplicates, fix missing values, standardize formats" },
  { text: "Analyze my data", icon: BarChart3, description: "Ask questions, get charts, discover insights" },
  { text: "Create a report", icon: FileText, description: "Generate a professional summary with visualizations" },
] as const;

export function EmptyState({ onChipClick }: EmptyStateProps) {
  return (
    <div className="flex h-full flex-col items-center justify-center px-6">
      <motion.div
        className="max-w-md text-center"
        variants={staggerContainer(0.1)}
        initial="hidden"
        animate="visible"
      >
        {/* Tiger icon with scale-in */}
        <motion.div
          variants={scaleIn}
          className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-2xl bg-brand-50"
        >
          <img src={tigerHeadSrc} alt="DataPilot" className="h-12 w-12 object-contain" />
        </motion.div>

        <motion.h1 variants={staggerItem} className="text-xl font-semibold text-ink">
          Welcome to <span className="text-brand-600">Data</span>
          <span className="text-gold-500">Pilot</span>
        </motion.h1>
        <motion.p variants={staggerItem} className="mt-2 text-[13px] leading-relaxed text-ink-tertiary">
          Upload a dataset or ask a question to start cleaning, analyzing, or reporting on your data.
        </motion.p>

        {/* Action cards - staggered */}
        <div className="mt-8 grid gap-3">
          {actions.map(({ text, icon: Icon, description }) => (
            <motion.button
              key={text}
              variants={staggerItem}
              whileHover={{ scale: 1.01, y: -2 }}
              whileTap={{ scale: 0.98 }}
              transition={spring.snappy}
              type="button"
              onClick={() => onChipClick(text)}
              className="flex items-center gap-4 rounded-xl border border-[var(--line)] bg-[var(--surface-primary)] p-4 text-left transition-colors duration-200 hover:border-brand-300 hover:bg-brand-50 hover:shadow-sm"
            >
              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-brand-50 text-brand-600">
                <Icon className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="text-[13px] font-medium text-ink">{text}</p>
                <p className="mt-0.5 text-[12px] text-ink-muted">{description}</p>
              </div>
            </motion.button>
          ))}
        </div>
      </motion.div>
    </div>
  );
}
