/**
 * The Library's own client (routes/documents.py): rename, move and re-type a
 * document, the Trash (list, restore, delete forever), folders and "New
 * Document". Kept out of
 * lib/api.ts, which is at its size ceiling, so the Library owns its calls; the
 * reads and writes the old Library already made (getDocuments, deleteDocument,
 * the concept scans, upload) stay where they were.
 */
import { fetchJSON } from "@/lib/api";
import type { DocFolder, Document as Doc } from "@/lib/types";

// Library: rename / re-file / re-categorise one document. Every field is
// optional and the server writes only the ones present, so a rename never
// disturbs the filing. `course_id` and `folder_id` accept an explicit null
// ("No Course" / unfiled), which is why they are optional-but-nullable rather
// than simply absent.
export interface DocumentPatch {
  file_name?: string;
  category?: Doc["category"];
  course_id?: string | null;
  folder_id?: string | null;
}

export const updateDocument = (documentId: string, userId: string, patch: DocumentPatch) =>
  fetchJSON<{ id: string }>(`/api/documents/doc/${documentId}`, {
    method: "PATCH",
    body: JSON.stringify({ user_id: userId, ...patch }),
  });

// Trash. A delete has always been a soft delete (`documents.deleted_at`), so
// this is a second read of the same table, plus the two ways out of it.
export const getTrashedDocuments = (userId: string) =>
  fetchJSON<{ documents: Doc[] }>(`/api/documents/user/${userId}/trash`);

export const restoreDocument = (documentId: string, userId: string) =>
  fetchJSON<{ restored: boolean }>(`/api/documents/doc/${documentId}/restore`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId }),
  });

/** Delete forever. Only ever valid for a document already in the Trash. */
export const purgeDocument = (documentId: string, userId: string) =>
  fetchJSON<{ deleted: boolean; purged: boolean }>(
    `/api/documents/doc/${documentId}?hard=1&user_id=${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );

/**
 * "New Document": an empty library document to write notes in. Unlike every
 * other row it has no file behind it, so the server marks it un-indexable.
 */
export const createBlankDocument = (
  userId: string,
  input: { file_name?: string; course_id?: string | null; folder_id?: string | null },
) =>
  fetchJSON<Doc>("/api/documents/blank", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, ...input }),
  });

// Folders — a named box inside a course that holds documents.
export const getFolders = (userId: string) =>
  fetchJSON<{ folders: DocFolder[] }>(
    `/api/documents/folders?user_id=${encodeURIComponent(userId)}`,
  );

export const createFolder = (userId: string, name: string, courseId: string | null) =>
  fetchJSON<DocFolder>("/api/documents/folders", {
    method: "POST",
    body: JSON.stringify({ user_id: userId, name, course_id: courseId }),
  });

export const renameFolder = (folderId: string, userId: string, name: string) =>
  fetchJSON<DocFolder>(`/api/documents/folders/${folderId}`, {
    method: "PATCH",
    body: JSON.stringify({ user_id: userId, name }),
  });

export const deleteFolder = (folderId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/documents/folders/${folderId}?user_id=${encodeURIComponent(userId)}`,
    { method: "DELETE" },
  );
