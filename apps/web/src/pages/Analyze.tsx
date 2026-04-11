import { useState, useRef, useEffect, useCallback } from "react";
import { useParams } from "react-router-dom";
import { Send, BarChart3, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { ChartRenderer } from "@/components/shared/ChartRenderer";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage, ChatSessionResponse, ChartConfig } from "@/types";

const PROMPT_CHIPS = [
  "Summarize key metrics",
  "Compare groups",
  "Detect anomalies",
  "Show distribution",
  "Top 10 values",
];

function extractCharts(msg: ChatMessage): ChartConfig[] {
  return msg.charts ?? [];
}

export default function Analyze() {
  const { datasetId } = useParams<{ datasetId: string }>();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [input, setInput] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [activeCharts, setActiveCharts] = useState<ChartConfig[]>([]);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  useEffect(() => {
    const assistantMsgs = messages.filter((m) => m.role === "assistant");
    if (assistantMsgs.length > 0) {
      const lastMsg = assistantMsgs[assistantMsgs.length - 1];
      const charts = extractCharts(lastMsg);
      if (charts.length > 0) setActiveCharts(charts);
    }
  }, [messages]);

  const handleSend = useCallback(async () => {
    const text = input.trim();
    if (!text || sending || !datasetId) return;

    setError(null);
    setSending(true);
    const userMsg: ChatMessage = { role: "user", content: text };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");

    try {
      const resp = await api
        .post(`analysis/${datasetId}/chat`, {
          json: { message: text, session_id: sessionId },
          timeout: 180_000,
        })
        .json<ChatSessionResponse>();

      setSessionId(resp.id);
      setMessages(resp.messages_json);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send message");
      setMessages((prev) => prev.slice(0, -1));
    } finally {
      setSending(false);
    }
  }, [input, sending, datasetId, sessionId]);

  const handleChip = (chip: string) => {
    setInput(chip);
    textareaRef.current?.focus();
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void handleSend();
    }
  };

  return (
    <div className="flex h-full flex-col lg:flex-row">
      {/* ── Chat panel ─────────────────────────────────────────────────── */}
      <div className="flex w-full shrink-0 flex-col border-b border-[var(--line)] lg:w-[420px] lg:border-b-0 lg:border-r">
        {/* Messages */}
        <div className="flex-1 space-y-3 overflow-y-auto p-4">
          {messages.length === 0 && !sending && (
            <div className="flex h-full flex-col items-center justify-center text-center">
              <BarChart3 className="h-10 w-10 text-ink-muted/30" />
              <p className="mt-3 text-[13px] text-ink-muted">
                Ask a question about your data
              </p>
            </div>
          )}

          {messages.map((msg, idx) => (
            <div
              key={idx}
              className={cn(
                "max-w-[85%] rounded-lg px-3.5 py-2.5 text-[13px] leading-relaxed animate-fade-in-up",
                msg.role === "user"
                  ? "ml-auto bg-brand-600 text-white"
                  : "bg-[var(--surface-raised)] text-ink",
              )}
              style={{ animationDelay: `${Math.min(idx * 50, 300)}ms`, animationFillMode: "both" }}
            >
              {msg.role === "user" ? (
                <div className="whitespace-pre-wrap">{msg.content}</div>
              ) : (
                <ReactMarkdown
                  remarkPlugins={[remarkGfm]}
                  components={{
                    h1: ({ children }) => <p className="font-semibold text-[14px] mb-1">{children}</p>,
                    h2: ({ children }) => <p className="font-semibold text-[13px] mb-1">{children}</p>,
                    h3: ({ children }) => <p className="font-medium text-[13px] mb-0.5">{children}</p>,
                    strong: ({ children }) => <strong className="font-semibold">{children}</strong>,
                    ul: ({ children }) => <ul className="list-disc list-inside space-y-0.5 my-1">{children}</ul>,
                    ol: ({ children }) => <ol className="list-decimal list-inside space-y-0.5 my-1">{children}</ol>,
                    li: ({ children }) => <li className="text-[13px]">{children}</li>,
                    p: ({ children }) => <p className="mb-1 last:mb-0">{children}</p>,
                    code: ({ children }) => <code className="rounded bg-black/10 px-1 py-0.5 font-mono text-[12px]">{children}</code>,
                  }}
                >
                  {msg.content}
                </ReactMarkdown>
              )}
            </div>
          ))}

          {sending && (
            <div className="flex items-center gap-2 text-[13px] text-ink-muted animate-fade-in">
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
              <span className="animate-pulse">Thinking...</span>
            </div>
          )}

          <div ref={messagesEndRef} />
        </div>

        {error && (
          <div className="mx-4 mb-2 rounded-md bg-coral-50 px-3 py-2 text-xs text-coral-700">
            {error}
          </div>
        )}

        {/* Chips */}
        <div className="flex flex-wrap gap-1.5 border-t border-[var(--line)] px-4 pt-3">
          {PROMPT_CHIPS.map((chip) => (
            <button
              key={chip}
              type="button"
              onClick={() => handleChip(chip)}
              className="rounded-full border border-[var(--line)] bg-[var(--surface-primary)] px-2.5 py-1 text-[11px] text-ink-secondary transition-all duration-150 hover:border-brand-300 hover:bg-brand-50 hover:text-brand-600 hover:shadow-sm active:scale-95"
            >
              {chip}
            </button>
          ))}
        </div>

        {/* Input */}
        <div className="flex items-end gap-2 border-t border-[var(--line)] p-3">
          <Textarea
            ref={textareaRef}
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Ask about your data..."
            className="min-h-[36px] max-h-[100px] flex-1 resize-none text-[13px]"
            rows={1}
          />
          <Button
            size="icon"
            className="h-9 w-9 shrink-0 bg-brand-600 text-white hover:bg-brand-700 transition-all duration-150 hover:shadow-md active:scale-90 disabled:opacity-40"
            onClick={() => void handleSend()}
            disabled={!input.trim() || sending}
          >
            <Send className="h-3.5 w-3.5" />
          </Button>
        </div>
      </div>

      {/* ── Results panel ──────────────────────────────────────────────── */}
      <div className="flex-1 overflow-y-auto p-6">
        {activeCharts.length > 0 ? (
          <div className="space-y-6">
            {activeCharts.map((chart, i) => (
              <div key={i} className="animate-fade-in-up" style={{ animationDelay: `${i * 100}ms`, animationFillMode: "both" }}>
                <ChartRenderer
                  config={chart}
                  data={chart.data.map((d) => ({
                    [chart.x_field]: d.x ?? d[chart.x_field as keyof typeof d],
                    [chart.y_field]: d.y ?? d[chart.y_field as keyof typeof d],
                  }))}
                />
              </div>
            ))}
          </div>
        ) : (
          <div className="flex h-full flex-col items-center justify-center text-center">
            <BarChart3 className="h-12 w-12 text-ink-muted/20" />
            <p className="mt-3 text-[13px] text-ink-muted">
              Results will appear here
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
