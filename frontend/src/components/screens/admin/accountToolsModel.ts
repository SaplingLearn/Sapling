import type {
  AdminAccountSummary, AdminAccountsMeta, AdminCopyPreview, AdminUserListItem,
} from "@/lib/types";

/** The pure state behind `AccountToolsDialog` (see that file for the flow). */

export type Action = "seed" | "wipe" | "push" | "pull";

export type ReviewData =
  | { kind: "local"; summary: AdminAccountSummary }
  | { kind: "copy"; preview: AdminCopyPreview };

export type ReviewState =
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "ready"; data: ReviewData };

/**
 * What the admin types to confirm, and the name the dialog uses for the
 * account. An undecryptable row has no email to type; its id is the
 * next-best unambiguous handle.
 */
export function accountHandles(user: AdminUserListItem): {
  target: string;
  targetIsEmail: boolean;
  who: string;
} {
  const target = (user.email ?? "").trim() || user.id;
  const targetIsEmail = Boolean(user.email && user.email.trim());
  const who = user.name || user.email || user.id;
  return { target, targetIsEmail, who };
}

/** A loaded copy review whose source or destination account doesn't exist. */
export function isCopyBlocked(review: ReviewState | null): boolean {
  return review?.status === "ready" && review.data.kind === "copy"
    ? !review.data.preview.source.summary.exists || !review.data.preview.destination.summary.exists
    : false;
}

/** The selected major, the peer environment, and this environment, off `/meta`. */
export function metaView(meta: AdminAccountsMeta | null, major: string) {
  return {
    selectedMajor: meta?.majors.find((m) => m.key === major) ?? null,
    peer: meta?.sync.peer_env ?? null,
    env: meta?.env ?? "",
  };
}

/** The final button runs only with a loaded, unblocked review, the typed handle, and nothing running. */
export function canConfirmReview({ ready, armed, busy, blocked, meta }: {
  ready: ReviewData | null;
  armed: boolean;
  busy: boolean;
  blocked: boolean;
  meta: AdminAccountsMeta | null;
}): boolean {
  return ready !== null && armed && !busy && !blocked && meta !== null;
}
