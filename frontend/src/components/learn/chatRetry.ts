import type { ChatMsg } from "../chat/ChatPanel";

/**
 * ADR 0020 Retry for a loop chat turn: drop the interrupted assistant bubble
 * and — when it sits directly before it — the student's bubble of the same
 * turn, so the re-send (which adds a fresh one) shows neither twice. The
 * legacy tutor's twin is screens/Learn.tsx `removeInterruptedTurn` (not
 * imported: that screen imports this one).
 */
export function dropInterruptedTurn(messages: ChatMsg[], interruptedId: string, retryText: string): ChatMsg[] {
  const i = messages.findIndex((m) => m.id === interruptedId);
  if (i === -1) return messages;
  const next = [...messages.slice(0, i), ...messages.slice(i + 1)];
  if (i > 0 && next[i - 1]?.role === "user" && next[i - 1].content === retryText) next.splice(i - 1, 1);
  return next;
}
