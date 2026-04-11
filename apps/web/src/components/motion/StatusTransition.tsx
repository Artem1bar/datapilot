import { motion, AnimatePresence } from "framer-motion";
import { Check, X } from "lucide-react";
import { cn } from "@/lib/utils";

interface StatusTransitionProps {
  status: "success" | "error" | null;
  size?: number;
  className?: string;
}

export function StatusTransition({ status, size = 24, className }: StatusTransitionProps) {
  return (
    <AnimatePresence mode="wait">
      {status && (
        <motion.div
          key={status}
          initial={{ scale: 0, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          exit={{ scale: 0.8, opacity: 0 }}
          transition={{ type: "spring", stiffness: 400, damping: 15 }}
          className={cn(
            "flex items-center justify-center rounded-full",
            status === "success" && "bg-teal-100 text-teal-600",
            status === "error" && "bg-coral-100 text-coral-600",
            className,
          )}
          style={{ width: size, height: size }}
        >
          {status === "success" ? (
            <motion.div
              initial={{ pathLength: 0 }}
              animate={{ pathLength: 1 }}
              transition={{ duration: 0.3, delay: 0.1 }}
            >
              <Check className="h-3.5 w-3.5" />
            </motion.div>
          ) : (
            <motion.div
              initial={{ rotate: -90, opacity: 0 }}
              animate={{ rotate: 0, opacity: 1 }}
              transition={{ duration: 0.2 }}
            >
              <X className="h-3.5 w-3.5" />
            </motion.div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}
