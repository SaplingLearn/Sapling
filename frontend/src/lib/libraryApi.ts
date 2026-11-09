// Library folders + document organisation (backend/routes/library_folders.py,
// mounted at /api/library). Identity comes from the session cookie.
import { fetchJSON } from "@/lib/api";

export interface LibraryFolder {
  id: string;
  course_id: string | null;
  name: string;
  created_at: string;
}

export interface LibraryState {
  folders: LibraryFolder[];
  /** document id -> folder id, for documents that sit in a folder */
  placements: Record<string, string>;
}

export const getLibraryFolders = () => fetchJSON<LibraryState>("/api/library/folders");

export const createLibraryFolder = (name: string, courseId: string | null) =>
  fetchJSON<LibraryFolder>("/api/library/folders", {
    method: "POST",
    body: JSON.stringify({ name, course_id: courseId }),
  });

export const renameLibraryFolder = (folderId: string, name: string) =>
  fetchJSON<LibraryFolder>(`/api/library/folders/${encodeURIComponent(folderId)}`, {
    method: "PATCH",
    body: JSON.stringify({ name }),
  });

export const deleteLibraryFolder = (folderId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/library/folders/${encodeURIComponent(folderId)}`, {
    method: "DELETE",
  });

export const moveDocumentsToFolder = (documentIds: string[], folderId: string | null) =>
  fetchJSON<{ moved: number; folder_id: string | null }>("/api/library/documents/folder", {
    method: "PUT",
    body: JSON.stringify({ document_ids: documentIds, folder_id: folderId }),
  });

export const renameLibraryDocument = (documentId: string, fileName: string) =>
  fetchJSON<{ id: string; file_name: string }>(
    `/api/library/documents/${encodeURIComponent(documentId)}`,
    { method: "PATCH", body: JSON.stringify({ file_name: fileName }) },
  );
