/**
 * Classifies a chat message into the action the app should take.
 *
 * Extracted from Chat.tsx's send handler so the routing rules have one home
 * and can be tested exhaustively. Precedence matters: a message that mentions
 * several things resolves to the highest-priority match, in this order —
 * clean → manipulate → analyze → report → chat. This mirrors the original
 * branch order in `handleSend` (clean and manipulate are checked before
 * analyze; report has no dedicated handler and falls through to chat).
 */
export type ChatIntent = "clean" | "manipulate" | "analyze" | "report" | "chat";

// Verb-led data edits handled by the manipulation parser. Word-boundaried so
// "drop" matches but "dropdown" does not.
const MANIPULATION_RE =
  /\b(delete|remove|drop|rename|sort|filter|add column|merge|format|move column|split|reorder|restructure)\b/;

export function detectIntent(text: string): ChatIntent {
  const lower = text.toLowerCase();
  if (lower.includes("clean")) return "clean";
  if (MANIPULATION_RE.test(lower)) return "manipulate";
  if (lower.includes("analyze") || lower.includes("analyse")) return "analyze";
  if (lower.includes("report")) return "report";
  return "chat";
}

/**
 * Whether an intent needs a dataset attached. Everything except free-form
 * chat operates on data, so an unattached session should prompt for a file.
 */
export function intentRequiresData(intent: ChatIntent): boolean {
  return intent !== "chat";
}
