import { Info, AlertCircle, CheckCircle2 } from "lucide-react";
import { cn } from "@/lib/utils";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessageV2 } from "@/types";

interface MessageBubbleProps {
  message: ChatMessageV2;
}

/* ── Markdown component overrides ───────────────────────────────────────── */

const markdownComponents = {
  h1: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-1 text-[14px] font-semibold">{children}</p>
  ),
  h2: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-1 text-[13px] font-semibold">{children}</p>
  ),
  h3: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-0.5 text-[13px] font-medium">{children}</p>
  ),
  strong: ({ children }: { children?: React.ReactNode }) => (
    <strong className="font-semibold">{children}</strong>
  ),
  ul: ({ children }: { children?: React.ReactNode }) => (
    <ul className="my-1 list-inside list-disc space-y-0.5">{children}</ul>
  ),
  ol: ({ children }: { children?: React.ReactNode }) => (
    <ol className="my-1 list-inside list-decimal space-y-0.5">{children}</ol>
  ),
  li: ({ children }: { children?: React.ReactNode }) => (
    <li className="text-[13px]">{children}</li>
  ),
  p: ({ children }: { children?: React.ReactNode }) => (
    <p className="mb-1 last:mb-0">{children}</p>
  ),
  code: ({ children }: { children?: React.ReactNode }) => (
    <code className="rounded bg-black/10 px-1 py-0.5 font-mono text-[12px]">
      {children}
    </code>
  ),
};

/* ── System message icons ───────────────────────────────────────────────── */

function getSystemIconElement(content: string, className: string) {
  const lc = content.toLowerCase();
  if (lc.includes("error") || lc.includes("failed")) {
    return <AlertCircle className={className} />;
  }
  if (lc.includes("complete") || lc.includes("success")) {
    return <CheckCircle2 className={className} />;
  }
  return <Info className={className} />;
}

/* ── Component ──────────────────────────────────────────────────────────── */

export function MessageBubble({ message }: MessageBubbleProps) {
  const { role, content } = message;

  // System messages: centered, compact, muted
  if (role === "system") {
    return (
      <div className="flex items-center justify-center gap-2 py-1 text-[12px] text-ink-muted">
        {getSystemIconElement(content, "h-3.5 w-3.5 shrink-0")}
        <span>{content}</span>
      </div>
    );
  }

  // User messages: right-aligned, brand color
  if (role === "user") {
    return (
      <div className="ml-auto max-w-[80%] rounded-2xl rounded-br-md bg-brand-600 px-4 py-2.5 text-[13px] leading-relaxed text-white">
        <div className="whitespace-pre-wrap">{content}</div>
      </div>
    );
  }

  // Assistant messages: left-aligned, surface color, markdown
  return (
    <div
      className={cn(
        "max-w-[80%] rounded-2xl rounded-bl-md bg-[var(--surface-raised)] px-4 py-2.5 text-[13px] leading-relaxed text-ink",
      )}
    >
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={markdownComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
