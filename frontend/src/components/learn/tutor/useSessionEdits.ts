"use client";
import { useCallback, type Dispatch, type SetStateAction } from "react";
import { deleteSession, renameSession, type LoopOpenSession } from "@/lib/api";
import { humanizeError } from "@/lib/errorMessage";
import type { TutorSessionRow } from "./sessions";

type Toast = { success: (m: string) => void; error: (m: string) => void };

/**
 * Rename and delete a session from the Tutor's lists (#866 K31), as the legacy
 * Learn screen's recent sessions do (PATCH / DELETE /api/learn/sessions/{id},
 * which serve loop sessions, a lazy one included). A rename shows at once and
 * is put back if the server refuses it; a delete leaves the lists once the
 * server has done it, and `onDeleted` lets the screen let go of it.
 */
export function useSessionEdits({ userId, toast, renameRecent, dropRecent, setOpenSessions, onDeleted }: {
  userId: string;
  toast: Toast;
  renameRecent: (id: string, topic: string) => void;
  dropRecent: (id: string) => void;
  setOpenSessions: Dispatch<SetStateAction<LoopOpenSession[] | null>>;
  onDeleted: (id: string) => void;
}) {
  const renameListed = useCallback((id: string, topic: string) => {
    renameRecent(id, topic);
    setOpenSessions((prev) => prev && prev.map((s) => (s.session_id === id ? { ...s, topic } : s)));
  }, [renameRecent, setOpenSessions]);

  const rename = useCallback(async (row: TutorSessionRow, topic: string) => {
    renameListed(row.id, topic);
    try {
      await renameSession(row.id, userId, topic);
    } catch (err) {
      renameListed(row.id, row.topic);
      toast.error(humanizeError(err, "Couldn't rename that session."));
    }
  }, [userId, toast, renameListed]);

  const remove = useCallback(async (row: TutorSessionRow) => {
    try {
      await deleteSession(row.id, userId);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't delete that session."));
      return;
    }
    dropRecent(row.id);
    setOpenSessions((prev) => prev && prev.filter((s) => s.session_id !== row.id));
    onDeleted(row.id);
    toast.success("Session deleted.");
  }, [userId, toast, dropRecent, setOpenSessions, onDeleted]);

  return { rename, remove };
}
