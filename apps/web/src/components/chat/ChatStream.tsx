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
  /** The session these messages belong to. Bound into every card action so an
   *  action dispatched after the user switches sessions still targets the
   *  owning session rather than whichever session is active at click time. */
  sessionId: string | null;
  sending?: boolean;
  onChipClick: (text: string) => void;
  onCardAction?: (action: string, data?: unknown, sessionId?: string) => void;
}

export function ChatStream({
  messages,
  sessionId,
  sending = false,
  onChipClick,
  onCardAction,
}: ChatStreamProps) {
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, sending]);

  const handleCardAction = onCardAction
    ? (action: string, data?: unknown) =>
        onCardAction(action, data, sessionId ?? undefined)
    : undefined;

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
              <CardRenderer payload={msg.card} onAction={handleCardAction} />
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
