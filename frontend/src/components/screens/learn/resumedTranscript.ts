// A resumed tutor session's transcript as the legacy Tutor (screens/Learn.tsx)
// draws it: its rows as chat messages, and the markdown profile they may use.

import type { ChatMsg } from "../../chat/ChatPanel";
import type { MarkdownProfile } from "../../chat/inertMarkdown";
import type { resumeSession } from "@/lib/api";

export type { MarkdownProfile };

type Resumed = Awaited<ReturnType<typeof resumeSession>>;

// #866 Z08: a learning-loop session's saved rows repeat class material verbatim
// (a check pose, an H2 passage, a worked sibling, a reference), and a row
// carries no provenance once saved. So when the legacy Tutor resumes one — the
// loop turned off by its kill switch or flag after the student used it — the
// whole transcript is drawn "inert", as LoopLearn draws it. Every other session
// (everything main can hold) stays "rich", exactly as before.
export function resumedTranscript(
  res: Resumed,
  msgId: () => string,
): { messages: ChatMsg[]; markdown: MarkdownProfile } {
  return {
    messages: (res.messages ?? []).map(m => ({
      id: msgId(),
      role: m.role === "user" ? "user" : "assistant",
      content: m.content,
    })),
    markdown: res.session.loop === true ? "inert" : "rich",
  };
}
