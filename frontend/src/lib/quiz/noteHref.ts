import { buildQuizHref } from "./source";

/** A concept quiz sourced from a note, with a return path that reopens it. */
export function quizHrefForNote(noteId: string, conceptNodeId: string): string {
  return buildQuizHref(
    { concept: conceptNodeId },
    { kind: "notes", returnTo: `/notetaker?note=${encodeURIComponent(noteId)}`, noteId },
  );
}
