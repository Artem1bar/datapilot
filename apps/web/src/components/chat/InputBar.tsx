import { useRef, useCallback } from "react";
import { Send } from "lucide-react";
import { motion } from "framer-motion";
import { Textarea } from "@/components/ui/textarea";
import { AttachMenu } from "./AttachMenu";
import { HotkeyChips } from "./HotkeyChips";
import { spring } from "@/lib/motion";

interface InputBarProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  onFileAttach: (file: File) => void;
  onTablePaste: (text: string) => void;
  onChipClick: (text: string) => void;
  sending?: boolean;
  disabled?: boolean;
  showChips?: boolean;
}

export function InputBar({
  value,
  onChange,
  onSend,
  onFileAttach,
  onTablePaste,
  onChipClick,
  sending = false,
  disabled = false,
  showChips = true,
}: InputBarProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (value.trim() && !sending && !disabled) {
          onSend();
        }
      }
    },
    [value, sending, disabled, onSend],
  );

  return (
    <div className="border-t border-[var(--line)] bg-[var(--surface-primary)] px-4 pb-4 pt-2">
      {/* Hotkey chips */}
      {showChips && <HotkeyChips onChipClick={onChipClick} />}

      {/* Input row */}
      <div className="flex items-end gap-2 rounded-xl border border-[var(--line)] bg-[var(--surface-canvas)] px-2 py-1.5 transition-all duration-200 focus-within:border-brand-400 focus-within:shadow-[0_0_0_2px_var(--brand-100)]">
        <AttachMenu
          onFileAttach={onFileAttach}
          onTablePaste={onTablePaste}
          disabled={disabled}
        />

        <Textarea
          ref={textareaRef}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Ask anything about your data or choose an action..."
          className="min-h-[36px] max-h-[84px] flex-1 resize-none border-0 bg-transparent text-[13px] shadow-none focus-visible:ring-0 placeholder:text-ink-muted"
          rows={1}
        />

        <motion.button
          whileHover={{ scale: 1.05 }}
          whileTap={{ scale: 0.9 }}
          transition={spring.snappy}
          className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-gold-500 text-brand-900 hover:bg-gold-600 transition-colors duration-150 hover:shadow-md disabled:opacity-40"
          onClick={onSend}
          disabled={!value.trim() || sending || disabled}
        >
          <Send className="h-3.5 w-3.5" />
        </motion.button>
      </div>

      <p className="mt-1.5 text-center text-[11px] text-ink-muted">
        DataPilot uses Claude AI. Always verify important results.
      </p>
    </div>
  );
}
