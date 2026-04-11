import { useEffect, useRef } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { MessageBubble } from "./MessageBubble";
import { TypingIndicator } from "./TypingIndicator";
import { CardRenderer } from "@/components/cards/CardRenderer";
import { EmptyState } from "./EmptyState";
import { fadeInUp } from "@/lib/motion";
import type { ChatMessageV2 } from "@/types";

interface ChatStreamProps {
  messages: readonly ChatMessageV2[];
  sending?: boolean;
  onChipClick: (text: string) => void;
  onCardAction?: (action: string, data?: unknown) => void;
}

export function ChatStream({
  messages,
  sending = false,
  onChipClick,
  onCardAction,
}: ChatStreamProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  if (messages.length === 0 && !sending) {
    return <EmptyState onChipClick={onChipClick} />;
  }

  return (
    <div className="flex-1 overflow-y-auto">
      <div className="mx-auto max-w-3xl space-y-3 px-4 py-6">
        {messages.map((msg) => (
          <motion.div
            key={msg.id}
            variants={fadeInUp}
            initial="hidden"
            animate="visible"
            layout
          >
            {msg.card ? (
              <CardRenderer payload={msg.card} onAction={onCardAction} />
            ) : (
              <MessageBubble message={msg} />
            )}
          </motion.div>
        ))}

        <AnimatePresence>
          {sending && <TypingIndicator />}
        </AnimatePresence>

        <div ref={endRef} />
      </div>
    </div>
  );
}
