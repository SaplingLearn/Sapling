/**
 * The per-document Notes page's client (routes/documents.py,
 * `/api/documents/doc/{id}/notes`): read (generated on the first read), save,
 * regenerate, and Ask Clov. Kept out of lib/api.ts, which is at its size
 * ceiling, so the page owns its calls.
 */
import { fetchJSON } from "@/lib/api";
import type { DocumentNotes, NotesChatTurn } from "@/lib/types";

// The per-document notes page (/library/[docId]/notes).
export const getDocumentNotes = (documentId: string, userId: string) =>
  fetchJSON<DocumentNotes>(
    `/api/documents/doc/${documentId}/notes?user_id=${encodeURIComponent(userId)}`,
  );

export const saveDocumentNotes = (
  documentId: string,
  userId: string,
  patch: { title?: string; content?: string; final?: boolean },
) =>
  fetchJSON<DocumentNotes>(`/api/documents/doc/${documentId}/notes`, {
    method: "PUT",
    body: JSON.stringify({ user_id: userId, ...patch }),
  });

/** Rebuild the notes from the source document, replacing the student's edits. */
export const regenerateDocumentNotes = (documentId: string, userId: string) =>
  fetchJSON<DocumentNotes>(`/api/documents/doc/${documentId}/notes/regenerate`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });

export const askDocumentNotes = (
  documentId: string,
  userId: string,
  body: { message: string; notes: string; quote?: string | null; history?: NotesChatTurn[] },
) =>
  fetchJSON<{ reply: string }>(`/api/documents/doc/${documentId}/notes/ask`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, ...body }),
  });
