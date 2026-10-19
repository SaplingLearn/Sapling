// Interrupted-turn helpers shared by classic Learn (ADR 0020) and the loop's
// Retry (redesign prompt 04). Pure, so both screens and their tests use one rule.
import type { ChatMsg } from "./ChatPanel";

/** Drop the interrupted assistant turn and — when it sits directly before it —
 *  the user turn of the same text, so a re-send (which appends a fresh user
 *  turn) never duplicates either. */
export function removeInterruptedTurn(
  messages: ChatMsg[],
  interruptedId: string,
  retryText: string,
): ChatMsg[] {
  const i = messages.findIndex((m) => m.id === interruptedId);
  if (i === -1) return messages;
  const next = [...messages.slice(0, i), ...messages.slice(i + 1)];
  if (i > 0 && next[i - 1]?.role === "user" && next[i - 1].content === retryText) {
    next.splice(i - 1, 1);
  }
  return next;
}

/** Did the server persist the interrupted turn after all? The loop saves the
 *  user row and the reply together only when a turn completes, so a turn that
 *  never finished leaves no row. A Stop (or a dropped connection) that races
 *  the server's completion can leave both rows, though: then the stored
 *  transcript holds one more user row with this text than the screen's settled
 *  turns do, and a re-send would duplicate it. `stored` is the server's
 *  transcript; `shown` is the screen's, including the unsent pair. */
export function interruptedTurnLanded(
  stored: Pick<ChatMsg, "role" | "content">[],
  shown: ChatMsg[],
  interruptedId: string,
  retryText: string,
): boolean {
  const same = (m: Pick<ChatMsg, "role" | "content">) => m.role === "user" && m.content.trim() === retryText.trim();
  const settled = removeInterruptedTurn(shown, interruptedId, retryText);
  return stored.filter(same).length > settled.filter(same).length;
}
