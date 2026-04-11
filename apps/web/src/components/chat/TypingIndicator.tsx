import { motion } from "framer-motion";

const dotVariants = {
  hidden: { y: 0 },
  visible: (i: number) => ({
    y: [0, -6, 0],
    transition: {
      duration: 0.6,
      repeat: Infinity,
      repeatDelay: 0.2,
      delay: i * 0.15,
      ease: "easeInOut" as const,
    },
  }),
};

export function TypingIndicator() {
  return (
    <motion.div
      className="flex items-center gap-2 py-1"
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      exit={{ opacity: 0, scale: 0.95 }}
      transition={{ duration: 0.2 }}
    >
      <div className="flex items-center gap-1 rounded-full bg-[var(--surface-raised)] px-3 py-2">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            custom={i}
            variants={dotVariants}
            initial="hidden"
            animate="visible"
            className="h-1.5 w-1.5 rounded-full bg-brand-400"
          />
        ))}
      </div>
      <span className="text-[12px] text-ink-muted">Thinking...</span>
    </motion.div>
  );
}
