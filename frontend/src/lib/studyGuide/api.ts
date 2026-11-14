/**
 * Study-guide client calls. One function per endpoint of
 * `backend/routes/study_guide.py`; shapes are in `./types`.
 */
import { API_URL, fetchJSON } from "@/lib/api";
import { streamSSE } from "@/lib/sse";

import type {
  AnswerResult,
  Block,
  CheckOptionId,
  GenerateMode,
  GenerationStep,
  GuideCard,
  GuideContent,
  GuideDetail,
  GuideOptions,
  GuidePatch,
  GuidePlan,
  GuideRequest,
  GuideState,
  Section,
} from "./types";

const base = (userId: string) => `/api/study-guide/${encodeURIComponent(userId)}`;
const guidePath = (userId: string, guideId: string) =>
  `${base(userId)}/guides/${encodeURIComponent(guideId)}`;
const blockPath = (userId: string, guideId: string, blockId: string) =>
  `${guidePath(userId, guideId)}/blocks/${encodeURIComponent(blockId)}`;
const post = (body?: unknown): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
});

/** Every guide the student has, newest first. */
export const listGuides = (userId: string) =>
  fetchJSON<{ guides: GuideCard[] }>(`${base(userId)}/guides`);

/** What a new guide for this class can be for, and from which materials. */
export const getGuideOptions = (userId: string, courseId: string, semester?: string | null) => {
  const query = new URLSearchParams({ course_id: courseId });
  if (semester) query.set("semester", semester);
  return fetchJSON<GuideOptions>(`${base(userId)}/options?${query}`);
};

/** The planned outline for these choices. No model runs. */
export const planGuide = (userId: string, request: GuideRequest, signal?: AbortSignal) =>
  fetchJSON<GuidePlan>(`${base(userId)}/plan`, { ...post(request), signal });

/** Create the guide row. Generation starts when the reader opens it. */
export const createGuide = (userId: string, request: GuideRequest) =>
  fetchJSON<{ id: string }>(`${base(userId)}/guides`, post(request));

export const getGuide = (userId: string, guideId: string) =>
  fetchJSON<GuideDetail>(guidePath(userId, guideId));

/** Mark sections read, save to or remove from the Library, leave feedback. */
export const patchGuide = (userId: string, guideId: string, patch: GuidePatch) =>
  fetchJSON<GuideState>(guidePath(userId, guideId), {
    method: "PATCH",
    body: JSON.stringify(patch),
  });

/** Rewrite one block. The rest of the guide stays as it is. */
export const regenerateBlock = (userId: string, guideId: string, blockId: string) =>
  fetchJSON<{ block: Block }>(`${blockPath(userId, guideId, blockId)}/regenerate`, post());

/** Answer a check-yourself question. Only the first answer moves mastery. */
export const answerCheck = (
  userId: string,
  guideId: string,
  blockId: string,
  optionId: CheckOptionId,
) =>
  fetchJSON<AnswerResult>(
    `${blockPath(userId, guideId, blockId)}/answer`,
    post({ option_id: optionId }),
  );

export interface GenerationHandlers {
  /** What the generation is doing now. */
  onStatus?: (label: string, step: GenerationStep) => void;
  /** The outline is ready: every section is listed, none written yet. */
  onOutline?: (content: GuideContent) => void;
  /** One section finished. */
  onSection?: (section: Section) => void;
  signal?: AbortSignal;
}

interface StreamEvent {
  type: "status" | "progress" | "done" | "error";
  step: string;
  message: string;
  data?: Record<string, unknown> | null;
}

/**
 * A generation that ended in an `error` event. `status` is the HTTP status the
 * event stands in for, when it carries one: a 409 is another run holding the
 * guide, exactly as when the request itself is answered with one.
 */
export class GuideGenerationError extends Error {
  constructor(
    message: string,
    readonly retryable: boolean,
    readonly status?: number,
  ) {
    super(message);
    this.name = "GuideGenerationError";
  }
}

/** No event for this long means the stream is dead, not slow. */
const STREAM_IDLE_MS = 300_000;

function dispatch(event: StreamEvent, handlers: GenerationHandlers): GuideDetail | null {
  const data = event.data ?? {};
  if (event.type === "status") {
    handlers.onStatus?.(event.message, data as unknown as GenerationStep);
  } else if (event.type === "progress" && event.step === "outline") {
    handlers.onOutline?.(data.content as GuideContent);
  } else if (event.type === "progress" && event.step === "section") {
    handlers.onSection?.(data.section as Section);
  } else if (event.type === "error") {
    throw new GuideGenerationError(
      event.message || "The guide could not be written.",
      data.retryable !== false,
      typeof data.status === "number" ? data.status : undefined,
    );
  } else if (event.type === "done") {
    return data.guide as GuideDetail;
  }
  return null;
}

/**
 * Run (or resume) a guide's generation and resolve with the finished guide.
 * A 409 means another request is already writing it: re-read the guide,
 * wait, and ask again.
 */
export async function generateGuide(
  userId: string,
  guideId: string,
  mode: GenerateMode,
  handlers: GenerationHandlers = {},
): Promise<GuideDetail> {
  const events = streamSSE<StreamEvent>(
    `${API_URL}${guidePath(userId, guideId)}/generate`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
      credentials: "include",
      signal: handlers.signal,
    },
    { idleTimeoutMs: STREAM_IDLE_MS },
  );
  for await (const { data } of events) {
    const finished = dispatch(data, handlers);
    if (finished) return finished;
  }
  throw new GuideGenerationError("The connection dropped before the guide was finished. Retry picks up where it stopped.", true);
}
