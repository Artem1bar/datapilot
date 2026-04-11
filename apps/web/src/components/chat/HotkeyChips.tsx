import { motion } from "framer-motion";
import { staggerContainer, staggerItem, spring } from "@/lib/motion";

interface HotkeyChipsProps {
  chips?: readonly string[];
  onChipClick: (text: string) => void;
}

const DEFAULT_CHIPS = [
  "Clean the data",
  "Analyze the data",
  "Create a report",
] as const;

export function HotkeyChips({ chips = DEFAULT_CHIPS, onChipClick }: HotkeyChipsProps) {
  return (
    <motion.div
      className="flex flex-wrap gap-1.5 px-1 pb-2"
      variants={staggerContainer(0.05)}
      initial="hidden"
      animate="visible"
    >
      {chips.map((chip) => (
        <motion.button
          key={chip}
          variants={staggerItem}
          whileHover={{ scale: 1.03, y: -1 }}
          whileTap={{ scale: 0.95 }}
          transition={spring.snappy}
          type="button"
          onClick={() => onChipClick(chip)}
          className="rounded-full border border-[var(--line)] bg-[var(--surface-primary)] px-3 py-1 text-[12px] text-ink-secondary transition-colors duration-150 hover:border-brand-300 hover:bg-brand-50 hover:text-brand-600 hover:shadow-sm"
        >
          {chip}
        </motion.button>
      ))}
    </motion.div>
  );
}
