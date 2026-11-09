"use client";
import React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Icon } from "../Icon";
import { FullHeightScreen } from "../FullHeightScreen";
import { Avatar } from "../Avatar";
import { CustomSelect } from "../CustomSelect";
import { Toggle } from "@/components/ui";
import { SocialRoomsSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useUser } from "@/context/UserContext";
import {
  recoverRealtimeAuth,
  superviseChannel,
  useRealtimeAuth,
  type RealtimeAuthMode,
} from "@/lib/realtimeAuth";
import { humanizeError } from "@/lib/errorMessage";
import {
  getUserRooms,
  createRoom,
  joinRoom,
  listPublicRooms,
  joinPublicRoom,
  getRoomMessages,
  sendRoomMessage,
  toggleRoomReaction,
  editRoomMessage,
  deleteRoomMessage,
  leaveRoom,
  kickMember,
  getRoomOverview,
  getRoomActivity,
  findStudyMatches,
  getStudents,
  fetchFriends,
  fetchFriendRequests,
  acceptFriendRequest,
  declineFriendRequest,
  cancelFriendRequest,
  removeFriend,
  type StudentRow,
} from "@/lib/api";
import type { PublicRoom, RoomMessageRow, RoomOverviewData, Friend } from "@/lib/types";

type IncomingFriendRequest = { id: string; from_user_id: string; name: string; created_at: string };
type OutgoingFriendRequest = { id: string; to_user_id: string; name: string; created_at: string };

type Tab = "overview" | "chat" | "match" | "activity" | "directory";
type Room = {
  id: string; name: string; invite_code: string; member_count: number;
  created_by?: string;
  // #405 columns (populated on create; older rows may carry nulls)
  topic?: string | null; course?: string | null; is_public?: boolean | null;
};

const EMOJI_50 = [
  "👍","🎉","❤️","🔥","🙌","💯","😂","😊","🤔","😮",
  "😢","🙏","👀","💡","✅","⚠️","🚀","🌱","📚","🧠",
  "⭐","✨","👏","💪","🎯","💬","☕","🍀","🌟","⚡",
  "🤝","✏️","📝","🧪","🔬","🎓","📊","🧩","🌈","🌻",
  "🥳","😎","🤷","🤯","🫡","🙈","🔖","📌","💭","💫",
];

function supabaseClient() {
  if (typeof window === "undefined") return null;
  try {
    // Lazy require so Supabase isn't pulled into the SSR bundle.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { getSupabase } = require("@/lib/supabase");
    return getSupabase();
  } catch {
    return null;
  }
}

// #124: room_messages.text is column-encrypted at rest; only the REST read path
// decrypts it. Realtime postgres_changes payloads carry the raw CIPHERTEXT, so
// rendering payload.new.text directly shows other users' messages as gibberish
// until a manual reload. Treat a realtime message event as a "something changed"
// signal and re-fetch through the decrypting REST endpoint instead of trusting
// the payload.
//
// (This fixes DISPLAY only. It does not address the realtime channel's missing
// authorization — that's the separate RLS/Realtime-Authorization work.)
type RealtimeMsgAction =
  | { type: "ignore" }
  | { type: "refetch" }
  | { type: "applyOwnFlags"; id: string; is_deleted: boolean; edited_at: string | null };

/** The Realtime client the token lifecycle drives (stable for the hook). */
function realtimeClient() {
  return supabaseClient()?.realtime ?? null;
}

/**
 * RLS step 2e (#115): whether the study-room `room:<id>` channel (room_messages
 * changes) may join right now. It only ever joins on the minted token:
 * room_messages has RLS on and no anon SELECT, so the anon key would
 * subscribe to nothing. (The presence/typing channel has its own rule: see
 * RoomChat.)
 *   - `token`: the minted token is applied; join, and re-join on loss.
 *   - `wait`: join nothing. No token yet (first fetch, a transient failure,
 *     or the last one expired), or none to be had (`unavailable`: the
 *     endpoint refused, logged by realtimeAuth). The room works over REST
 *     meanwhile: history on open, own sends, and a poll of the latest page
 *     every REST_POLL_MS while the tab is visible.
 */
export type RoomRealtimePlan = "wait" | "token";

export function planRoomRealtime(authMode: RealtimeAuthMode): RoomRealtimePlan {
  return authMode === "token" ? "token" : "wait";
}

/** While the room is not live, re-fetch the latest page this often (only
 * while the tab is visible), so classmates' messages still arrive. */
export const REST_POLL_MS = 12_000;
/** Show "Live updates paused" only once the room has been off the live
 * channel this long: the first token fetch must not flash it. */
export const PAUSED_NOTICE_DELAY_MS = 5_000;

export function planMessageRealtimeAction(
  event: "INSERT" | "UPDATE",
  row: { id?: string; user_id?: string; is_deleted?: boolean; edited_at?: string | null } | null | undefined,
  currentUserId: string | null | undefined,
): RealtimeMsgAction {
  if (!row || !row.id) return { type: "ignore" };
  const isOwn = row.user_id === currentUserId;
  if (event === "INSERT") {
    // Own inserts are shown optimistically and reconciled by the POST response;
    // foreign inserts carry ciphertext text → re-fetch decrypted via REST.
    return isOwn ? { type: "ignore" } : { type: "refetch" };
  }
  // UPDATE (edit / soft-delete): own edits keep their optimistic plaintext and
  // take only the server-side flags; foreign edits re-fetch (ciphertext text).
  if (isOwn) {
    return {
      type: "applyOwnFlags",
      id: row.id,
      is_deleted: !!row.is_deleted,
      edited_at: row.edited_at ?? null,
    };
  }
  return { type: "refetch" };
}

/**
 * #764: fold a fresh latest page into what the chat already holds. A realtime
 * refetch used to REPLACE the list with the latest page, dropping every
 * earlier page the user had loaded. Server rows win inside the latest page's
 * window; older loaded rows and still-unsent optimistic `tmp_` rows are kept.
 */
export function mergeLatestMessages<T extends { id: string; created_at: string }>(
  prev: T[],
  latest: T[],
): T[] {
  if (latest.length === 0) return prev;
  const latestIds = new Set(latest.map((m) => m.id));
  const pending = prev.filter((m) => m.id.startsWith("tmp_"));
  const windowStart = Date.parse(latest[0].created_at);
  const older = prev.filter(
    (m) => !m.id.startsWith("tmp_") && !latestIds.has(m.id) && Date.parse(m.created_at) < windowStart,
  );
  return [...older, ...latest, ...pending];
}

function CreateJoinBar({ onDone }: { onDone: () => void }) {
  const { userId } = useUser();
  const toast = useToast();
  const [mode, setMode] = React.useState<"idle" | "create" | "join">("idle");
  const [value, setValue] = React.useState("");
  // #405 create-form fields: optional labeling + the public flag
  // (false = invite-only; true = listed and joinable without an invite).
  const [topic, setTopic] = React.useState("");
  const [course, setCourse] = React.useState("");
  const [isPublic, setIsPublic] = React.useState(false);

  const reset = () => {
    setMode("idle");
    setValue("");
    setTopic("");
    setCourse("");
    setIsPublic(false);
  };

  const submit = async () => {
    if (!value.trim() || !userId) return;
    try {
      if (mode === "create") {
        await createRoom(userId, value.trim(), {
          topic: topic.trim() || undefined,
          course: course.trim() || undefined,
          is_public: isPublic,
        });
      } else if (mode === "join") await joinRoom(userId, value.trim());
      toast.success(mode === "create" ? "Room created" : "Joined room");
      reset();
      onDone();
    } catch (err) {
      toast.error(String(err));
    }
  };

  if (mode === "idle") {
    return (
      <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
        <button data-testid="social-create-room" className="btn btn--sm btn--primary" style={{ flex: 1 }} onClick={() => setMode("create")}>
          <Icon name="plus" size={12} /> Create
        </button>
        <button data-testid="social-join-room" className="btn btn--sm" style={{ flex: 1 }} onClick={() => setMode("join")}>Join</button>
      </div>
    );
  }

  const inputStyle: React.CSSProperties = {
    flex: 1, padding: "6px 10px",
    border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
    fontSize: 12, background: "var(--bg-panel)",
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 6, marginTop: 10 }}>
      <div style={{ display: "flex", gap: 6 }}>
        <input
          data-testid="social-create-join-input"
          autoFocus
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") reset(); }}
          placeholder={mode === "create" ? "Room name" : "Invite code"}
          style={inputStyle}
        />
        <button data-testid="social-create-join-submit" className="btn btn--sm btn--primary" onClick={submit}>Go</button>
      </div>
      {mode === "create" && (
        <>
          <input
            data-testid="social-create-topic"
            value={topic}
            onChange={(e) => setTopic(e.target.value)}
            placeholder="Topic (optional)"
            style={inputStyle}
          />
          <input
            data-testid="social-create-course"
            value={course}
            onChange={(e) => setCourse(e.target.value)}
            placeholder="Course (optional)"
            style={inputStyle}
          />
          <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-dim)" }}>
            <input
              data-testid="social-create-public"
              type="checkbox"
              checked={isPublic}
              onChange={(e) => setIsPublic(e.target.checked)}
            />
            Public — anyone can find and join without an invite
          </label>
        </>
      )}
    </div>
  );
}

function PublicRoomsList({ excludeIds, onJoined }: { excludeIds: string[]; onJoined: () => void }) {
  const { userId } = useUser();
  const toast = useToast();
  const [rooms, setRooms] = React.useState<PublicRoom[]>([]);
  const [joining, setJoining] = React.useState<string | null>(null);

  const refresh = React.useCallback(async () => {
    if (!userId) return;
    try {
      setRooms((await listPublicRooms(userId)).rooms);
    } catch (err) {
      // Never swallow: an empty list has to mean "no public rooms", not
      // "the fetch broke" (#463/#185 convention). This is a secondary
      // surface, so it toasts rather than taking over with a banner.
      toast.error(`Couldn't load public rooms. ${String(err)}`);
    }
  }, [userId, toast]);

  React.useEffect(() => { refresh(); }, [refresh]);

  const discoverable = rooms.filter((r) => !excludeIds.includes(r.id));
  if (discoverable.length === 0) return null;

  const join = async (roomId: string) => {
    if (!userId || joining) return;
    setJoining(roomId);
    try {
      await joinPublicRoom(userId, roomId);
      toast.success("Joined room");
      onJoined();
      // onJoined reloads MY rooms; this list owns its own data, so refresh
      // it too or the joined room lingers as "discoverable" (#485 review).
      await refresh();
    } catch (err) {
      toast.error(String(err));
    } finally {
      setJoining(null);
    }
  };

  return (
    <div style={{ marginTop: 14 }}>
      <div className="label-micro" style={{ marginBottom: 6 }}>Public rooms</div>
      {discoverable.map((r) => (
        <div
          key={r.id}
          style={{
            display: "flex", alignItems: "center", gap: 8,
            padding: "8px 10px", marginBottom: 4,
            border: "1px solid var(--border)", borderRadius: "var(--r-md)",
          }}
        >
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{r.name}</div>
            <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
              {r.topic ? `${r.topic} · ` : ""}{r.member_count} member{r.member_count === 1 ? "" : "s"}
            </div>
          </div>
          <button
            data-testid={`social-public-join-${r.id}`}
            className="btn btn--sm"
            disabled={joining !== null}
            onClick={() => join(r.id)}
          >
            {joining === r.id ? "Joining…" : "Join"}
          </button>
        </div>
      ))}
    </div>
  );
}

function FriendRow({ friend, onRemove }: { friend: Friend; onRemove: () => void | Promise<void> }) {
  const remove = useConfirm(onRemove);
  return (
    <div
      data-testid={`social-friend-row-${friend.user_id}`}
      style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 0" }}
    >
      <Avatar name={friend.name} size={26} />
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontSize: 12, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
          {friend.name}
        </div>
        <div style={{ fontSize: 10, color: "var(--text-muted)" }}>
          Lv {friend.level} · {friend.total_xp} XP
        </div>
      </div>
      <button
        data-testid={`social-friend-remove-${friend.user_id}`}
        className={`btn btn--sm ${remove.armed ? "btn--danger" : "btn--ghost"}`}
        onClick={remove.trigger}
        style={remove.armed ? { background: "var(--err-soft)", color: "var(--err)" } : undefined}
      >
        {remove.armed ? "Click again" : "Remove"}
      </button>
    </div>
  );
}

/**
 * Friends panel: friends list + incoming/outgoing requests, sitting above
 * the rooms list in the Social sidebar. Every mutation (accept/decline/
 * remove) refetches both lists from the server rather than mutating local
 * state optimistically — a failed accept (someone else already actioned the
 * request, or it was withdrawn: 403/404) shouldn't leave a row the server
 * doesn't agree exists, so we tell the user AND resync to the truth.
 */
export function FriendsPanel() {
  const { userId } = useUser();
  const toast = useToast();
  const [friends, setFriends] = React.useState<Friend[]>([]);
  const [incoming, setIncoming] = React.useState<IncomingFriendRequest[]>([]);
  const [outgoing, setOutgoing] = React.useState<OutgoingFriendRequest[]>([]);
  const [loading, setLoading] = React.useState(true);

  const refresh = React.useCallback(async () => {
    if (!userId) return;
    try {
      const [f, r] = await Promise.all([fetchFriends(userId), fetchFriendRequests(userId)]);
      setFriends(f.friends || []);
      setIncoming(r.incoming || []);
      setOutgoing(r.outgoing || []);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't load friends."));
    } finally {
      setLoading(false);
    }
  }, [userId, toast]);

  React.useEffect(() => { refresh(); }, [refresh]);

  const remove = async (friendId: string) => {
    if (!userId) return;
    try {
      await removeFriend(friendId, userId);
      toast.success("Friend removed");
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't remove that friend."));
    } finally {
      await refresh();
    }
  };

  const accept = async (requestId: string) => {
    if (!userId) return;
    try {
      await acceptFriendRequest(requestId, userId);
      toast.success("Friend request accepted");
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't accept that request."));
    } finally {
      await refresh();
    }
  };

  const decline = async (requestId: string) => {
    if (!userId) return;
    try {
      await declineFriendRequest(requestId, userId);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't decline that request."));
    } finally {
      await refresh();
    }
  };

  // #764: the sender can withdraw a request that is still pending.
  const cancel = async (requestId: string) => {
    if (!userId) return;
    try {
      await cancelFriendRequest(requestId, userId);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't cancel that request."));
    } finally {
      await refresh();
    }
  };

  if (loading) {
    return (
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
        <div className="label-micro" style={{ marginBottom: 6 }}>Friends</div>
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Loading…</div>
      </div>
    );
  }

  return (
    <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)", maxHeight: 320, overflowY: "auto" }}>
      <div className="label-micro" style={{ marginBottom: 6 }}>Friends</div>

      {incoming.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: 4 }}>
            <span style={{ fontSize: 11, fontWeight: 600 }}>Incoming requests</span>
            <span className="chip chip--accent" style={{ fontSize: 10 }}>{incoming.length}</span>
          </div>
          {incoming.map((r) => (
            <div
              key={r.id}
              data-testid={`social-friend-incoming-${r.id}`}
              style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}
            >
              <Avatar name={r.name} size={24} />
              <div style={{ flex: 1, minWidth: 0, fontSize: 12, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.name}
              </div>
              <button
                data-testid={`social-friend-accept-${r.id}`}
                className="btn btn--sm btn--primary"
                onClick={() => accept(r.id)}
              >
                Accept
              </button>
              <button
                data-testid={`social-friend-decline-${r.id}`}
                className="btn btn--sm btn--ghost"
                onClick={() => decline(r.id)}
              >
                Decline
              </button>
            </div>
          ))}
        </div>
      )}

      {outgoing.length > 0 && (
        <div style={{ marginBottom: 12 }}>
          <div style={{ fontSize: 11, fontWeight: 600, marginBottom: 4 }}>Outgoing</div>
          {outgoing.map((r) => (
            <div
              key={r.id}
              data-testid={`social-friend-outgoing-${r.id}`}
              style={{ display: "flex", alignItems: "center", gap: 8, padding: "4px 0" }}
            >
              <Avatar name={r.name} size={24} />
              <div style={{ flex: 1, minWidth: 0, fontSize: 12, color: "var(--text-dim)", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                {r.name}
              </div>
              <span className="chip" style={{ fontSize: 10 }}>Pending</span>
              <button
                data-testid={`social-friend-cancel-${r.id}`}
                className="btn btn--sm btn--ghost"
                onClick={() => cancel(r.id)}
              >
                Cancel
              </button>
            </div>
          ))}
        </div>
      )}

      {friends.length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No friends yet.</div>
      ) : (
        friends.map((f) => (
          <FriendRow key={f.user_id} friend={f} onRemove={() => remove(f.user_id)} />
        ))
      )}
    </div>
  );
}

/**
 * Intrinsic pixel size of a picked image file, or null if it can't be read
 * (#315).
 *
 * Measured from an object URL rather than after upload, so the dimensions
 * travel with the message that creates it and history renders reserved from
 * the first paint. Resolving null on error is deliberate: a message that
 * cannot be measured should still send, it just renders unreserved like it
 * did before.
 */
async function readImageSize(file: File): Promise<{ width: number; height: number } | undefined> {
  if (typeof window === "undefined" || !file.type.startsWith("image/")) return undefined;
  const url = URL.createObjectURL(file);
  try {
    return await new Promise((resolve) => {
      const img = new Image();
      img.onload = () =>
        resolve(
          img.naturalWidth && img.naturalHeight
            ? { width: img.naturalWidth, height: img.naturalHeight }
            : undefined,
        );
      img.onerror = () => resolve(undefined);
      img.src = url;
    });
  } finally {
    URL.revokeObjectURL(url);
  }
}

function RoomChat({ roomId, members, realtimePlan, realtimeEpoch }: {
  roomId: string;
  members: { user_id: string; name: string }[];
  /** RLS step 2e: owned by the Social screen, so room/tab switches keep the token. */
  realtimePlan: RoomRealtimePlan;
  /** Bumps each time a token is (re)applied after a gap: re-join then. */
  realtimeEpoch: number;
}) {
  const { userId, userName } = useUser();
  const toast = useToast();
  const [messages, setMessages] = React.useState<RoomMessageRow[]>([]);
  const [input, setInput] = React.useState("");
  const [replyTo, setReplyTo] = React.useState<RoomMessageRow | null>(null);
  const [editing, setEditing] = React.useState<string | null>(null);
  const [editValue, setEditValue] = React.useState("");
  const [picker, setPicker] = React.useState<string | null>(null);
  const [menu, setMenu] = React.useState<string | null>(null);
  const [typingUsers, setTypingUsers] = React.useState<Set<string>>(new Set());
  const [mentionState, setMentionState] = React.useState<{ query: string; index: number } | null>(null);
  const [hasMore, setHasMore] = React.useState(false);
  const [loadingEarlier, setLoadingEarlier] = React.useState(false);
  const scrollRef = React.useRef<HTMLDivElement>(null);
  const inputRef = React.useRef<HTMLTextAreaElement>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const typingChannelRef = React.useRef<any>(null);

  const load = React.useCallback(async () => {
    try {
      const res = await getRoomMessages(roomId, { limit: 50 });
      setMessages(res.messages || []);
      setHasMore(Boolean(res.has_more));
    } catch (err) {
      console.error("messages load failed", err);
    }
  }, [roomId]);

  React.useEffect(() => { load(); }, [load]);

  // #764: a realtime "something changed" refetch MERGES the latest page into
  // the list instead of replacing it, so earlier pages the user loaded stay.
  // hasMore is untouched: it describes the oldest page held, not the newest.
  const refreshLatest = React.useCallback(async () => {
    try {
      const res = await getRoomMessages(roomId, { limit: 50 });
      setMessages(prev => mergeLatestMessages(prev, res.messages || []));
    } catch (err) {
      console.error("messages refresh failed", err);
    }
  }, [roomId]);

  // Not live (no token yet, a transient failure, or none to be had): poll the
  // latest page so classmates' messages still arrive, paused while the tab is
  // hidden and caught up at once when it comes back. The merge dedups.
  const [pausedLong, setPausedLong] = React.useState(false);
  React.useEffect(() => {
    if (realtimePlan === "token") return;
    const visible = () => document.visibilityState === "visible";
    const notice = setTimeout(() => setPausedLong(true), PAUSED_NOTICE_DELAY_MS);
    const poll = setInterval(() => { if (visible()) void refreshLatest(); }, REST_POLL_MS);
    const onVisibility = () => { if (visible()) void refreshLatest(); };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      clearTimeout(notice);
      clearInterval(poll);
      document.removeEventListener("visibilitychange", onVisibility);
      setPausedLong(false);
    };
  }, [realtimePlan, refreshLatest]);
  const livePaused = realtimePlan !== "token" && pausedLong;

  // Realtime subscriptions. RLS step 2e (#115): `realtimePlan` (Social owns
  // the token lifecycle) decides when: they join on the minted token only, and
  // re-join whenever Realtime drops the channel (it closes it once the token
  // expires).
  React.useEffect(() => {
    if (realtimePlan === "wait") return;
    const supa = supabaseClient();
    if (!supa) return;

    const build = () => supa
      .channel(`room:${roomId}`)
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "room_messages", filter: `room_id=eq.${roomId}` },
        (payload: any) => {
          // #124: foreign inserts carry ciphertext text — re-fetch decrypted via
          // REST rather than appending payload.new. Own echoes are ignored (the
          // optimistic UI + POST reconciliation already have them).
          const action = planMessageRealtimeAction("INSERT", payload.new, userId);
          if (action.type === "refetch") void refreshLatest();
        })
      .on("postgres_changes",
        { event: "UPDATE", schema: "public", table: "room_messages", filter: `room_id=eq.${roomId}` },
        (payload: any) => {
          const action = planMessageRealtimeAction("UPDATE", payload.new, userId);
          if (action.type === "refetch") {
            // #124: foreign edit/delete — re-fetch decrypted via REST.
            void refreshLatest();
          } else if (action.type === "applyOwnFlags") {
            // Own edit/delete keeps its optimistic plaintext; take server flags.
            setMessages(prev => prev.map(m =>
              m.id === action.id
                ? { ...m, is_deleted: action.is_deleted, edited_at: action.edited_at ?? m.edited_at }
                : m,
            ));
          }
        });
      // #231: the room_reactions realtime subscription was dead code — the
      // table is not in the supabase_realtime publication, so these handlers
      // never fired. Removed. Reactions still update on load/refresh via REST;
      // live reactions can be restored post-RLS by publishing room_reactions
      // with a membership-scoped policy (see
      // docs/security/realtime-jwt-bridge-design.md).

    return superviseChannel({
      topic: `room:${roomId}`,
      create: build,
      remove: (channel) => supa.removeChannel(channel),
      // Every (re)join starts after messages may have been sent: catch up
      // (the merge dedups).
      onSubscribed: () => { void refreshLatest(); },
      onLost: () => recoverRealtimeAuth(),
    });
  }, [roomId, refreshLatest, userId, realtimePlan, realtimeEpoch]);

  // Presence / typing channel. NOT gated on the minted token, on purpose:
  // `presence:<id>` is a PUBLIC Realtime channel, which Realtime never checks
  // against RLS (that needs a private channel and a realtime.messages
  // policy). It reads no table, and anyone holding the public anon key can
  // join it whether or not this client waits for a token, so waiting would
  // protect nothing and only cost typing indicators whenever the token is
  // missing. It therefore joins on whatever key the client holds (the anon
  // key, or the minted token once `setAuth` applies it, which realtime-js
  // pushes to joined channels); when Realtime closes it on that token's
  // expiry, superviseChannel re-joins after a refresh.
  React.useEffect(() => {
    const supa = supabaseClient();
    if (!supa || !userId) return;
    const build = () => {
      const ch = supa.channel(`presence:${roomId}`, { config: { presence: { key: userId } } });
      return ch
        .on("presence", { event: "sync" }, () => {
          const state = ch.presenceState();
          const typers = new Set<string>();
          Object.entries(state).forEach(([uid, arr]: [string, any]) => {
            if (uid === userId) return;
            const p = arr?.[0];
            if (p?.typing && Date.now() - (p.last || 0) < 3000) typers.add(p.name || uid);
          });
          setTypingUsers(typers);
        });
    };
    const track = (ch: ReturnType<typeof build>) =>
      ch.track({ name: userName || "Anonymous", typing: false, last: Date.now() });

    const stop = superviseChannel({
      topic: `presence:${roomId}`,
      create: build,
      remove: (ch) => supa.removeChannel(ch),
      onSubscribed: (ch) => {
        typingChannelRef.current = ch;
        void track(ch);
      },
      onLost: () => {
        typingChannelRef.current = null;
        return recoverRealtimeAuth();
      },
    });
    return () => {
      stop();
      typingChannelRef.current = null;
    };
  }, [roomId, userId, userName]);

  React.useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages.length]);

  const announceTyping = React.useRef(
    debounce((channel: any, name: string) => {
      channel?.track({ name, typing: false, last: Date.now() });
    }, 2500),
  );

  const onInputChange = (v: string) => {
    setInput(v);
    const ch = typingChannelRef.current;
    if (ch) {
      ch.track({ name: userName || "Anonymous", typing: true, last: Date.now() });
      announceTyping.current(ch, userName || "Anonymous");
    }
    // Mention detection
    const match = v.match(/@([\w-]*)$/);
    if (match) setMentionState({ query: match[1].toLowerCase(), index: 0 });
    else setMentionState(null);
  };

  const filteredMentions = React.useMemo(() => {
    if (!mentionState) return [];
    const q = mentionState.query;
    return members.filter(m => m.name.toLowerCase().includes(q)).slice(0, 6);
  }, [mentionState, members]);

  const applyMention = (name: string) => {
    setInput(prev => prev.replace(/@([\w-]*)$/, `@${name.replace(/\s+/g, "")} `));
    setMentionState(null);
    inputRef.current?.focus();
  };

  const send = async () => {
    const text = input.trim();
    if (!text || !userId) return;
    const tmpId = `tmp_${Date.now()}_${Math.random()}`;
    const tmp: RoomMessageRow = {
      id: tmpId,
      user_id: userId,
      user_name: userName || "Me",
      text,
      image_url: null,
      created_at: new Date().toISOString(),
      reply_to_id: replyTo?.id || null,
      is_deleted: false,
      edited_at: null,
      reply_to: replyTo ? { id: replyTo.id, user_name: replyTo.user_name, text: replyTo.text } : null,
      reactions: [],
    };
    setMessages(prev => [...prev, tmp]);
    setInput("");
    const r = replyTo;
    setReplyTo(null);
    try {
      // Replace the optimistic temp row with the server's decrypted message
      // (matched by real id). This is the authoritative dedup: the realtime
      // INSERT echo can't reconcile because it carries ciphertext, never the
      // plaintext we appended (issue #131).
      const res = await sendRoomMessage(roomId, userId, userName || "Me", text, undefined, r?.id);
      const saved = res?.message as RoomMessageRow | undefined;
      if (saved?.id) {
        // Drop the tmp row, then upsert the saved row by id (replace if the
        // realtime echo already landed it, else append). reply_to/reactions
        // come from the optimistic tmp since the POST response omits them.
        const reconciled: RoomMessageRow = {
          ...saved,
          reply_to: saved.reply_to ?? tmp.reply_to,
          reactions: saved.reactions ?? [],
        };
        setMessages(prev => {
          const next = prev.filter(m => m.id !== tmpId);
          return next.some(m => m.id === saved.id)
            ? next.map(m => m.id === saved.id ? { ...m, ...reconciled, reactions: m.reactions ?? reconciled.reactions } : m)
            : [...next, reconciled];
        });
      }
    } catch (err) {
      setMessages(prev => prev.filter(m => m.id !== tmpId));
      toast.error(`Send failed: ${String(err)}`);
    }
  };

  const handleEditSave = async (id: string) => {
    const text = editValue.trim();
    if (!text || !userId) return;
    try {
      await editRoomMessage(roomId, id, userId, text);
      setMessages(prev => prev.map(m => m.id === id ? { ...m, text, edited_at: new Date().toISOString() } : m));
      toast.success("Edited");
      setEditing(null);
      setEditValue("");
    } catch (err) {
      toast.error(`Edit failed: ${String(err)}`);
    }
  };

  const handleDelete = async (m: RoomMessageRow) => {
    if (!userId) return;
    try {
      await deleteRoomMessage(roomId, m.id, userId);
      setMessages(prev => prev.map(x => x.id === m.id ? { ...x, is_deleted: true, text: null } : x));
    } catch (err) {
      toast.error(`Delete failed: ${String(err)}`);
    }
  };

  const handleReaction = async (messageId: string, emoji: string) => {
    if (!userId) return;
    try {
      const res = await toggleRoomReaction(roomId, messageId, userId, emoji);
      // #764: apply the toggle locally. A full load() here replaced the list
      // with the latest page, so reacting to an older message dropped it.
      setMessages(prev => prev.map(m => {
        if (m.id !== messageId) return m;
        const list = m.reactions || [];
        const withEmoji = list.some(r => r.emoji === emoji) ? list : [...list, { emoji, user_ids: [] }];
        const reactions = withEmoji
          .map(r => {
            if (r.emoji !== emoji) return r;
            const rest = r.user_ids.filter(id => id !== userId);
            return { ...r, user_ids: res.added ? [...rest, userId] : rest };
          })
          .filter(r => r.user_ids.length > 0);
        return { ...m, reactions };
      }));
    } catch (err) {
      toast.error(`Reaction failed: ${String(err)}`);
    }
    setPicker(null);
  };

  const handleImage = async (file: File) => {
    const supa = supabaseClient();
    if (!supa || !userId) {
      toast.error("Image uploads require Supabase storage.");
      return;
    }
    try {
      // Measure before upload so the transcript can reserve the exact box.
      // Failure is non-fatal: without dimensions the attachment just renders
      // unreserved, which is the pre-#315 behaviour.
      const imageSize = await readImageSize(file);
      const path = `${roomId}/${userId}-${Date.now()}-${file.name}`;
      const up = await supa.storage.from("chat-images").upload(path, file);
      if (up.error) throw up.error;
      const pub = supa.storage.from("chat-images").getPublicUrl(path);
      const url: string = pub.data.publicUrl;
      const res = await sendRoomMessage(roomId, userId, userName || "Me", "", url, undefined, imageSize);
      // Append from the POST response (own realtime echoes are skipped to avoid
      // duplicates), deduping by id in case the echo already landed.
      const saved = res?.message as RoomMessageRow | undefined;
      if (saved?.id) {
        setMessages(prev => prev.some(m => m.id === saved.id)
          ? prev
          : [...prev, { ...saved, reply_to: saved.reply_to ?? null, reactions: saved.reactions ?? [] }]);
      }
      toast.success("Image sent");
    } catch (err) {
      toast.error(`Upload failed: ${String(err)}`);
    }
  };

  const loadEarlier = async () => {
    if (loadingEarlier || !hasMore || messages.length === 0) return;
    setLoadingEarlier(true);
    const scrollEl = scrollRef.current;
    const prevHeight = scrollEl?.scrollHeight ?? 0;
    try {
      const oldest = messages[0];
      const res = await getRoomMessages(roomId, { before: oldest.created_at, limit: 50 });
      const existing = new Set(messages.map(m => m.id));
      const older = (res.messages || []).filter(m => !existing.has(m.id));
      setMessages(prev => [...older, ...prev]);
      setHasMore(Boolean(res.has_more));
      requestAnimationFrame(() => {
        if (scrollEl) scrollEl.scrollTop = scrollEl.scrollHeight - prevHeight;
      });
    } catch (err) {
      toast.error(`Couldn't load earlier messages: ${String(err)}`);
    } finally {
      setLoadingEarlier(false);
    }
  };

  const renderText = (text: string | null) => {
    if (!text) return null;
    // Escape HTML, then highlight @Mentions against member names.
    const safe = text.replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c] || c));
    const memberSet = new Set(members.map(m => m.name.replace(/\s+/g, "")));
    const out = safe.replace(/@([\w-]+)/g, (full, name) => {
      if (memberSet.has(name)) return `<span style="color:var(--accent);font-weight:600">${full}</span>`;
      return full;
    });
    return <span dangerouslySetInnerHTML={{ __html: out }} />;
  };

  return (
    <>
      <div style={{ padding: "6px 20px 0", fontSize: 11, color: "var(--text-muted)", minHeight: 18, display: "flex", justifyContent: "space-between", gap: 12 }}>
        <span>{typingUsers.size > 0 && `${Array.from(typingUsers).join(", ")} typing…`}</span>
        {livePaused && (
          <span
            data-testid="social-chat-live-paused"
            role="status"
            title="New messages are checked every few seconds until the live connection is back."
          >
            Live updates paused
          </span>
        )}
      </div>
      <div
        ref={scrollRef}
        data-testid="social-chat-messages"
        style={{ flex: 1, overflowY: "auto", padding: "12px 24px", display: "flex", flexDirection: "column", gap: 14 }}
      >
        {hasMore && (
          <div style={{ textAlign: "center" }}>
            <button data-testid="social-chat-load-earlier" className="btn btn--ghost btn--sm" onClick={loadEarlier} disabled={loadingEarlier}>
              {loadingEarlier ? "Loading…" : "Load earlier messages"}
            </button>
          </div>
        )}
        {messages.length === 0 && (
          <div style={{ textAlign: "center", color: "var(--text-muted)", fontSize: 12 }}>No messages yet — say hi.</div>
        )}
        {messages.map((m) => {
          const self = m.user_id === userId;
          const isMenuOpen = menu === m.id;
          const isEditing = editing === m.id;
          return (
            <div key={m.id} data-testid={`social-chat-message-${m.id}`} style={{ display: "flex", gap: 10, alignSelf: self ? "flex-end" : "flex-start", maxWidth: "72%", position: "relative" }} className="fade-in">
              {!self && <Avatar name={m.user_name} size={32} />}
              <div style={{ position: "relative" }}>
                {!self && <div style={{ fontSize: 11, color: "var(--text-dim)", fontWeight: 600, marginBottom: 2 }}>{m.user_name}</div>}
                {m.reply_to && (
                  <div style={{ fontSize: 11, color: "var(--text-muted)", borderLeft: "1px solid var(--border)", paddingLeft: 6, marginBottom: 4 }}>
                    ↪ <strong>{m.reply_to.user_name}</strong>: {m.reply_to.text?.slice(0, 60) || "(deleted)"}
                  </div>
                )}
                {m.is_deleted ? (
                  <div style={{ padding: "8px 12px", borderRadius: "var(--r-md)", background: "var(--bg-subtle)", color: "var(--text-muted)", fontStyle: "italic", fontSize: 13 }}>
                    Message deleted
                  </div>
                ) : isEditing ? (
                  <div style={{ display: "flex", gap: 6 }}>
                    <input
                      data-testid="social-chat-edit-input"
                      autoFocus
                      value={editValue}
                      onChange={e => setEditValue(e.target.value)}
                      onKeyDown={e => {
                        if (e.key === "Enter") handleEditSave(m.id);
                        if (e.key === "Escape") { setEditing(null); setEditValue(""); }
                      }}
                      style={{
                        padding: "6px 10px", border: "1px solid var(--border)",
                        borderRadius: "var(--r-sm)", fontSize: 13, background: "var(--bg-panel)",
                      }}
                    />
                    <button data-testid="social-chat-edit-save" className="btn btn--sm btn--primary" onClick={() => handleEditSave(m.id)}>Save</button>
                    <button data-testid="social-chat-edit-cancel" className="btn btn--sm btn--ghost" onClick={() => { setEditing(null); setEditValue(""); }}>
                      <Icon name="x" size={11} />
                    </button>
                  </div>
                ) : (
                  <div
                    onClick={() => setMenu(v => v === m.id ? null : m.id)}
                    style={{
                      padding: "8px 12px", borderRadius: "var(--r-md)",
                      background: self ? "var(--accent)" : "var(--bg-panel)",
                      color: self ? "var(--accent-fg)" : "var(--text)",
                      border: self ? "none" : "1px solid var(--border)",
                      fontSize: 13.5, whiteSpace: "pre-wrap", cursor: "pointer",
                    }}
                  >
                    {m.image_url && (
                      <img
                        src={m.image_url}
                        alt="attachment"
                        loading="lazy"
                        decoding="async"
                        {...(m.image_width && m.image_height
                          ? { width: m.image_width, height: m.image_height }
                          : {})}
                        style={{
                          maxWidth: 260,
                          borderRadius: "var(--r-sm)",
                          marginBottom: m.text ? 6 : 0,
                          // With intrinsic dimensions the browser reserves the
                          // box from the aspect ratio before the lazily-loaded
                          // bytes arrive, so scrolling back through history
                          // does not shift the transcript. Safari has no scroll
                          // anchoring to hide it, which is why this matters.
                          ...(m.image_width && m.image_height
                            ? {
                                aspectRatio: `${m.image_width} / ${m.image_height}`,
                                height: "auto",
                                // Belt and braces against dimensions that do
                                // not match the bytes: the server bounds them,
                                // but a merely WRONG pair would otherwise
                                // stretch the image instead of letterboxing.
                                objectFit: "contain" as const,
                                // maxWidth alone cannot cap a very tall image
                                // once the ratio drives the height.
                                maxHeight: 320,
                              }
                            : {}),
                        }}
                      />
                    )}
                    {renderText(m.text)}
                    {m.edited_at && <span style={{ fontSize: 10, opacity: 0.6, marginLeft: 6 }}>(edited)</span>}
                  </div>
                )}
                {m.reactions.length > 0 && (
                  <div style={{ display: "flex", gap: 4, marginTop: 4, flexWrap: "wrap" }}>
                    {m.reactions.map((r) => (
                      <button
                        key={r.emoji}
                        data-testid={`social-chat-reaction-${r.emoji}`}
                        onClick={() => handleReaction(m.id, r.emoji)}
                        style={{
                          fontSize: 11, padding: "2px 8px",
                          background: r.user_ids.includes(userId) ? "var(--accent-soft)" : "var(--bg-panel)",
                          color: r.user_ids.includes(userId) ? "var(--accent)" : "var(--text)",
                          border: "1px solid var(--border)", borderRadius: "var(--r-full)",
                        }}
                      >
                        {r.emoji} {r.user_ids.length}
                      </button>
                    ))}
                  </div>
                )}
                {isMenuOpen && !m.is_deleted && (
                  <div style={{ position: "absolute", top: -32, right: 0, display: "flex", gap: 4, background: "var(--bg-panel)", border: "1px solid var(--border-strong)", borderRadius: "var(--r-full)", padding: 4, boxShadow: "var(--shadow-md)" }}>
                    <button data-testid="social-chat-message-react" className="btn btn--ghost btn--sm" title="React" onClick={(e) => { e.stopPropagation(); setPicker(m.id); }}>
                      😊
                    </button>
                    <button data-testid="social-chat-message-reply" className="btn btn--ghost btn--sm" title="Reply" onClick={(e) => { e.stopPropagation(); setReplyTo(m); setMenu(null); inputRef.current?.focus(); }}>
                      ↪
                    </button>
                    {self && (
                      <>
                        <button data-testid="social-chat-message-edit" className="btn btn--ghost btn--sm" title="Edit" onClick={(e) => { e.stopPropagation(); setEditing(m.id); setEditValue(m.text || ""); setMenu(null); }}>
                          <Icon name="pencil" size={11} />
                        </button>
                        <button data-testid="social-chat-message-delete" className="btn btn--ghost btn--sm" title="Delete" onClick={(e) => { e.stopPropagation(); handleDelete(m); setMenu(null); }}>
                          <Icon name="x" size={11} />
                        </button>
                      </>
                    )}
                  </div>
                )}
                {picker === m.id && (
                  <div style={{ position: "absolute", top: 20, right: 0, zIndex: 20, background: "var(--bg-panel)", border: "1px solid var(--border-strong)", borderRadius: "var(--r-md)", padding: 10, boxShadow: "var(--shadow-lg)", display: "grid", gridTemplateColumns: "repeat(10, 1fr)", gap: 4, width: 340 }}>
                    {EMOJI_50.map((e) => (
                      <button key={e} data-testid={`social-chat-emoji-${e}`} onClick={() => handleReaction(m.id, e)} style={{ fontSize: 16, padding: 4, borderRadius: 4 }}>{e}</button>
                    ))}
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {replyTo && (
        <div style={{ padding: "6px 20px", borderTop: "1px solid var(--border)", background: "var(--bg-subtle)", fontSize: 11, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div style={{ color: "var(--text-dim)" }}>
            Replying to <strong>{replyTo.user_name}</strong>: {replyTo.text?.slice(0, 80) || "(attachment)"}
          </div>
          <button data-testid="social-chat-reply-cancel" className="btn btn--ghost btn--sm" onClick={() => setReplyTo(null)}>
            <Icon name="x" size={11} />
          </button>
        </div>
      )}

      <div style={{ position: "relative", padding: "12px 20px", borderTop: "1px solid var(--border)", background: "var(--bg-panel)" }}>
        {mentionState && filteredMentions.length > 0 && (
          <div style={{ position: "absolute", left: 20, bottom: 70, background: "var(--bg-panel)", border: "1px solid var(--border-strong)", borderRadius: "var(--r-md)", boxShadow: "var(--shadow-md)", overflow: "hidden", minWidth: 200, zIndex: 10 }}>
            {filteredMentions.map((m, i) => (
              <button
                key={m.user_id}
                data-testid={`social-chat-mention-${m.user_id}`}
                onClick={() => applyMention(m.name)}
                style={{
                  display: "block", width: "100%", textAlign: "left",
                  padding: "6px 10px", fontSize: 12,
                  background: i === (mentionState?.index || 0) ? "var(--bg-subtle)" : "transparent",
                }}
              >
                @{m.name.replace(/\s+/g, "")}
              </button>
            ))}
          </div>
        )}
        <div style={{ display: "flex", gap: 8, alignItems: "center", background: "var(--bg-subtle)", borderRadius: "var(--r-full)", padding: "6px 14px", border: "1px solid var(--border)" }}>
          <textarea
            ref={inputRef}
            data-testid="social-chat-input"
            value={input}
            rows={1}
            onChange={(e) => onInputChange(e.target.value)}
            onKeyDown={(e) => {
              if (mentionState && filteredMentions.length > 0) {
                if (e.key === "ArrowDown") { e.preventDefault(); setMentionState(s => s && ({ ...s, index: Math.min(filteredMentions.length - 1, s.index + 1) })); return; }
                if (e.key === "ArrowUp") { e.preventDefault(); setMentionState(s => s && ({ ...s, index: Math.max(0, s.index - 1) })); return; }
                if (e.key === "Tab" || e.key === "Enter") {
                  e.preventDefault();
                  applyMention(filteredMentions[mentionState.index || 0].name);
                  return;
                }
                if (e.key === "Escape") { setMentionState(null); return; }
              }
              if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(); }
            }}
            placeholder="Message the room… (@ to mention)"
            style={{
              flex: 1, border: 0, background: "transparent",
              fontSize: 14, padding: "6px 0", resize: "none", fontFamily: "inherit", color: "inherit",
            }}
          />
          <input
            ref={fileRef}
            data-testid="social-chat-image-input"
            type="file"
            accept="image/*"
            hidden
            onChange={e => {
              const f = e.target.files?.[0];
              if (f) handleImage(f);
              e.target.value = "";
            }}
          />
          <button data-testid="social-chat-attach" className="btn btn--ghost btn--sm" onClick={() => fileRef.current?.click()} title="Attach image">
            <Icon name="doc" size={13} />
          </button>
          <button data-testid="social-chat-send" className="btn btn--primary btn--sm" onClick={send} disabled={!input.trim()}>
            <Icon name="send" size={13} />
          </button>
        </div>
      </div>
    </>
  );
}

function debounce<T extends (...args: any[]) => void>(fn: T, ms: number): T {
  let t: ReturnType<typeof setTimeout> | null = null;
  return ((...args: any[]) => {
    if (t) clearTimeout(t);
    t = setTimeout(() => fn(...args), ms);
  }) as T;
}

function RoomOverview({ roomId, onChange }: { roomId: string; onChange: () => void }) {
  const { userId } = useUser();
  const toast = useToast();
  const search = useSearchParams();
  const suggestedId = search.get("suggest");
  const [data, setData] = React.useState<RoomOverviewData | null>(null);
  React.useEffect(() => {
    getRoomOverview(roomId).then(setData).catch(console.error);
  }, [roomId]);

  const refresh = () => getRoomOverview(roomId).then(setData).catch(console.error);
  // Ownership, not authorship: the backend's kick gate keys on owner_id
  // (#405, transferable later). Fall back to created_by for rows predating
  // the 0038 backfill.
  const roomOwnerId = data?.room?.owner_id ?? data?.room?.created_by;
  const isLeader = roomOwnerId === userId;

  const comparison = React.useMemo(() => {
    if (!data || !suggestedId || suggestedId === userId) return null;
    const me = data.members.find(m => m.user_id === userId);
    const partner = data.members.find(m => m.user_id === suggestedId);
    if (!me || !partner) return null;
    const myByName = new Map<string, number>();
    for (const n of me.graph.nodes || []) {
      myByName.set((n.concept_name || "").trim().toLowerCase(), n.mastery_score || 0);
    }
    const entries = (partner.graph.nodes || [])
      .filter(n => !n.is_subject_root)
      .map(n => {
        const key = (n.concept_name || "").trim().toLowerCase();
        return {
          name: n.concept_name,
          partner_mastery: n.mastery_score || 0,
          my_mastery: myByName.get(key) ?? 0,
          delta: (n.mastery_score || 0) - (myByName.get(key) ?? 0),
        };
      })
      .filter(e => e.partner_mastery > 0.1)
      .sort((a, b) => b.delta - a.delta);
    return { partner, entries };
  }, [data, suggestedId, userId]);

  const leave = useConfirm(async () => {
    try {
      await leaveRoom(roomId, userId);
      toast.success("Left the room");
      onChange();
    } catch (err) {
      toast.error(`Leave failed: ${String(err)}`);
    }
  });

  if (!data) return <div style={{ flex: 1, padding: 32, color: "var(--text-muted)" }}>Loading…</div>;
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px" }}>
      <div className="card" style={{ padding: "var(--pad-lg)", marginBottom: 20 }}>
        <div className="label-micro">AI room summary</div>
        <div style={{ fontSize: 14, lineHeight: 1.6, marginTop: 8, color: "var(--text-dim)" }}>
          {data.ai_summary || "No summary yet."}
        </div>
      </div>

      {comparison && (
        <div className="card" style={{ padding: "var(--pad-lg)", marginBottom: 20 }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", marginBottom: 10 }}>
            <div className="label-micro">Comparison with {comparison.partner.name}</div>
            <span className="chip chip--accent">Top concepts where they have the edge</span>
          </div>
          {comparison.entries.length === 0 ? (
            <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No comparable concepts yet.</div>
          ) : (
            <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
              {comparison.entries.slice(0, 8).map(e => (
                <div key={e.name} style={{ display: "grid", gridTemplateColumns: "1fr 2fr 2fr", gap: 10, alignItems: "center" }}>
                  <div style={{ fontSize: 12, fontWeight: 500, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{e.name}</div>
                  <MasteryBar label="You" value={e.my_mastery} color="var(--accent)" />
                  <MasteryBar label={comparison.partner.name} value={e.partner_mastery} color="#8a7bc4" dashed />
                </div>
              ))}
            </div>
          )}
        </div>
      )}
      <div className="card" style={{ padding: "var(--pad-lg)" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
          <div className="label-micro">Members</div>
          <button
            data-testid="social-room-leave"
            className={`btn btn--sm ${leave.armed ? "btn--danger" : ""}`}
            onClick={leave.trigger}
            style={leave.armed ? { background: "var(--err-soft)", color: "var(--err)" } : undefined}
          >
            {leave.armed ? "Click again to leave" : <><Icon name="logout" size={11} /> Leave room</>}
          </button>
        </div>
        {data.members.map((m, i) => (
          <MemberRow
            key={m.user_id}
            member={m}
            isLeader={(data.room.owner_id ?? data.room.created_by) === m.user_id}
            canKick={isLeader && m.user_id !== userId}
            onKick={async () => {
              try {
                await kickMember(roomId, m.user_id, userId);
                toast.success(`Removed ${m.name}`);
                refresh();
              } catch (err) {
                toast.error(`Kick failed: ${String(err)}`);
              }
            }}
            last={i === data.members.length - 1}
          />
        ))}
      </div>
    </div>
  );
}

function MasteryBar({ label, value, color, dashed }: { label: string; value: number; color: string; dashed?: boolean }) {
  const pct = Math.max(0, Math.min(100, Math.round(value * 100)));
  return (
    <div>
      <div style={{ display: "flex", justifyContent: "space-between", fontSize: 10, color: "var(--text-muted)", marginBottom: 3 }}>
        <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{label}</span>
        <span className="mono">{pct}%</span>
      </div>
      <div style={{
        height: 6, background: "var(--bg-soft)", borderRadius: "var(--r-full)", overflow: "hidden",
        outline: dashed ? `1px dashed ${color}` : "none", outlineOffset: 1,
      }}>
        <div style={{ width: "100%", height: "100%", background: color, transformOrigin: "left", transform: `scaleX(${pct / 100})`, transition: "transform var(--dur) var(--ease)" }} />
      </div>
    </div>
  );
}

function MemberRow({
  member, isLeader, canKick, onKick, last,
}: {
  member: { user_id: string; name: string };
  isLeader: boolean;
  canKick: boolean;
  onKick: () => void | Promise<void>;
  last: boolean;
}) {
  const kick = useConfirm(onKick);
  return (
    <div data-testid={`social-member-${member.user_id}`} style={{
      display: "flex", alignItems: "center", gap: 10,
      padding: "10px 0", borderBottom: last ? "none" : "1px solid var(--border)",
    }}>
      <Avatar name={member.name} size={30} />
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{member.name}</div>
      </div>
      {isLeader && <span className="chip chip--accent">Leader</span>}
      <Link
        href={`/profile/${encodeURIComponent(member.user_id)}`}
        className="btn btn--sm btn--ghost"
        title="View profile"
        style={{ textDecoration: "none" }}
      >
        <Icon name="search" size={11} /> Profile
      </Link>
      {canKick && (
        <button
          data-testid={`social-member-kick-${member.user_id}`}
          className={`btn btn--sm ${kick.armed ? "btn--danger" : "btn--ghost"}`}
          onClick={kick.trigger}
          style={kick.armed ? { background: "var(--err-soft)", color: "var(--err)" } : undefined}
        >
          {kick.armed ? "Click again" : "Kick"}
        </button>
      )}
    </div>
  );
}

function StudyMatch({ roomId }: { roomId: string }) {
  const { userId } = useUser();
  const toast = useToast();
  const [matches, setMatches] = React.useState<any[]>([]);
  const [loading, setLoading] = React.useState(false);
  const [popupShown, setPopupShown] = React.useState(false);

  const run = async () => {
    if (!userId) return;
    setLoading(true);
    try {
      const res = await findStudyMatches(roomId, userId);
      setMatches(res.matches || []);
      const top = (res.matches || [])[0];
      if (!popupShown && top) {
        setPopupShown(true);
        toast.success(`Best match: ${top.partner?.name} at ${Math.round((top.compatibility_score || 0) * 100)}%`);
      }
    } catch (err) {
      toast.error(`Matching failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  };
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: 32 }}>
      <div style={{ maxWidth: 800, margin: "0 auto" }}>
        <div className="card" style={{ padding: "var(--pad-xl)", textAlign: "center", background: "linear-gradient(135deg, var(--accent-soft), var(--bg-panel))" }}>
          <Icon name="sparkle" size={28} />
          <div className="h-serif" style={{ fontSize: 24, margin: "12px 0 6px", fontWeight: 500 }}>Find your study match</div>
          <div style={{ color: "var(--text-dim)", marginBottom: 20 }}>
            We&apos;ll pair you with members whose knowledge complements yours.
          </div>
          <button data-testid="social-match-run" className="btn btn--primary" onClick={run} disabled={loading}>
            {loading ? "Finding…" : "Find matches"}
          </button>
        </div>
        {matches.length > 0 && (
          <>
            <div className="label-micro" style={{ margin: "24px 0 12px" }}>Suggested partners</div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
              {matches.map((m, i) => {
                const partnerId = m.partner?.id || m.partner?.user_id;
                const inner = (
                  <>
                    <Avatar name={m.partner?.name || "?"} size={48} />
                    <div style={{ flex: 1 }}>
                      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                        <div style={{ fontWeight: 600 }}>{m.partner?.name}</div>
                        <span className="mono" style={{ color: "var(--accent)", fontSize: 15 }}>
                          {Math.round((m.compatibility_score || 0) * 100)}%
                        </span>
                      </div>
                      <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 4, lineHeight: 1.5 }}>{m.summary}</div>
                    </div>
                  </>
                );
                return partnerId ? (
                  <Link
                    key={partnerId}
                    href={`/profile/${encodeURIComponent(partnerId)}`}
                    className="card"
                    style={{ padding: "var(--pad-lg)", display: "flex", gap: 14, textDecoration: "none", color: "inherit" }}
                  >
                    {inner}
                  </Link>
                ) : (
                  <div key={i} className="card" style={{ padding: "var(--pad-lg)", display: "flex", gap: 14 }}>
                    {inner}
                  </div>
                );
              })}
            </div>
          </>
        )}
      </div>
    </div>
  );
}

function RoomActivity({ roomId }: { roomId: string }) {
  const [activities, setActivities] = React.useState<any[]>([]);
  React.useEffect(() => {
    getRoomActivity(roomId).then((r) => setActivities(r.activities || [])).catch(console.error);
  }, [roomId]);
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px" }}>
      {activities.length === 0 && <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No activity yet.</div>}
      {activities.map((a) => (
        <div key={a.id} style={{ display: "flex", gap: 12, padding: "14px 0", borderBottom: "1px solid var(--border)" }}>
          <Avatar name={a.user_name} size={36} />
          <div style={{ flex: 1 }}>
            <div style={{ fontSize: 13 }}>
              <strong>{a.user_name}</strong> {a.activity_type}{" "}
              <span style={{ color: "var(--accent)", fontWeight: 600 }}>{a.concept_name}</span>
            </div>
            <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
              {new Date(a.created_at).toLocaleString()}
            </div>
          </div>
        </div>
      ))}
    </div>
  );
}

function SchoolDirectory() {
  const { userId } = useUser();
  const [students, setStudents] = React.useState<StudentRow[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [q, setQ] = React.useState("");

  React.useEffect(() => {
    getStudents().then(r => setStudents(r.students || [])).catch(console.error).finally(() => setLoading(false));
  }, []);

  const filtered = React.useMemo(() => {
    const t = q.trim().toLowerCase();
    if (!t) return students;
    return students.filter(s =>
      s.name.toLowerCase().includes(t) ||
      s.courses.some(c => c.toLowerCase().includes(t))
    );
  }, [q, students]);

  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "24px 32px" }}>
      <div style={{ maxWidth: 980, margin: "0 auto" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div>
            <div className="label-micro">Directory</div>
            <div className="h-serif" style={{ fontSize: 22 }}>Students at your school</div>
          </div>
          <input
            data-testid="social-directory-search"
            value={q}
            onChange={e => setQ(e.target.value)}
            placeholder="Search by name, course, concept"
            style={{
              padding: "6px 12px", fontSize: 12, minWidth: 260,
              border: "1px solid var(--border)", borderRadius: "var(--r-full)",
              background: "var(--bg-panel)",
            }}
          />
        </div>
        {loading ? (
          <div style={{ color: "var(--text-muted)", fontSize: 13 }}>Loading directory…</div>
        ) : (
          // Roster list replaces the previous 280px card grid —
          // directories of people should scan like a class roster,
          // not a stock-photo team page.
          <div style={{ display: "flex", flexDirection: "column" }}>
            {filtered.map((s, i) => (
              <Link
                key={s.user_id}
                href={`/profile/${encodeURIComponent(s.user_id)}`}
                style={{
                  padding: "14px 4px",
                  borderTop: i === 0 ? "none" : "1px solid var(--border)",
                  display: "flex", gap: 14, alignItems: "center",
                  textDecoration: "none", color: "inherit",
                  transition: "background var(--dur-fast) var(--ease)",
                }}
              >
                <Avatar name={s.name} size={40} />
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="h-serif" style={{ fontSize: 15, fontWeight: 500 }}>{s.name}</span>
                    {s.user_id === userId && <span className="chip chip--accent">You</span>}
                  </div>
                  {s.courses.length > 0 && (
                    <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 2 }}>
                      {s.courses.slice(0, 3).join(" · ")}
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 6 }}>
                    {s.streak}d streak
                  </div>
                </div>
              </Link>
            ))}
            {filtered.length === 0 && (
              <div style={{ color: "var(--text-muted)", fontSize: 13 }}>No matches.</div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

export function Social() {
  const search = useSearchParams();
  const { userId, userReady } = useUser();
  // RLS step 2e (#115): the Realtime token lifecycle lives here, not in the
  // per-room RoomChat, so a room or tab switch neither drops the token nor
  // re-mints. Only once the session is known (no request before it, and a
  // sign-in as someone else starts a fresh lifecycle).
  const realtimeAuth = useRealtimeAuth(realtimeClient, userReady ? userId : null);
  const realtimePlan = planRoomRealtime(realtimeAuth.mode);
  const realtimeEpoch = realtimePlan === "token" ? realtimeAuth.epoch : 0;
  const [rooms, setRooms] = React.useState<Room[]>([]);
  const [activeId, setActiveId] = React.useState<string | null>(null);
  const [tab, setTab] = React.useState<Tab>("chat");
  const [overview, setOverview] = React.useState<RoomOverviewData | null>(null);
  const [loading, setLoading] = React.useState(true);

  const suggest = search.get("suggest");
  React.useEffect(() => { if (suggest) setTab("overview"); }, [suggest]);

  const load = React.useCallback(async () => {
    if (!userId) return;
    try {
      const res = await getUserRooms(userId);
      const list = (res.rooms || []) as Room[];
      setRooms(list);
      // #764: keep the selection only while it is still one of our rooms —
      // after a leave (or a kick) the old id would leave the pane blank.
      setActiveId(prev => (prev && list.some(r => r.id === prev) ? prev : list[0]?.id || null));
    } catch (err) {
      console.error("rooms load failed", err);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  React.useEffect(() => { if (userReady && userId) load(); }, [userReady, userId, load]);

  React.useEffect(() => {
    if (!activeId) { setOverview(null); return; }
    // #764: drop a slower response for a room we have already switched away
    // from, so room A's member list never lands on room B.
    let current = true;
    getRoomOverview(activeId)
      .then(data => { if (current) setOverview(data); })
      .catch(console.error);
    return () => { current = false; };
  }, [activeId]);

  const active = rooms.find((r) => r.id === activeId);
  const members = (overview?.members || []).map(m => ({ user_id: m.user_id, name: m.name }));

  return (
    <FullHeightScreen direction="row">
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {tab === "directory" ? <SchoolDirectory /> : active ? (
          <>
            <div style={{ padding: "18px 24px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div data-testid="social-room-name" className="h-serif" style={{ fontSize: 22, fontWeight: 500 }}>{active.name}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
                  <CopyChip code={active.invite_code} />
                  <span>{active.member_count} members</span>
                </div>
              </div>
              <Toggle
                options={[
                  { value: "overview", label: "Overview" },
                  { value: "chat", label: "Chat" },
                  { value: "match", label: "Study match" },
                  { value: "activity", label: "Activity" },
                ]}
                value={tab}
                onChange={setTab}
                size="sm"
              />
            </div>
            {/* #764: keyed by room so replyTo, edit state, matches and any
                in-flight load reset on a room switch instead of leaking. */}
            {tab === "chat" && (
              <RoomChat
                key={active.id}
                roomId={active.id}
                members={members}
                realtimePlan={realtimePlan}
                realtimeEpoch={realtimeEpoch}
              />
            )}
            {tab === "overview" && <RoomOverview key={active.id} roomId={active.id} onChange={load} />}
            {tab === "match" && <StudyMatch key={active.id} roomId={active.id} />}
            {tab === "activity" && <RoomActivity key={active.id} roomId={active.id} />}
          </>
        ) : (
          <div style={{ flex: 1, display: "grid", placeItems: "center", color: "var(--text-muted)" }}>
            Select or create a room to begin.
          </div>
        )}
      </div>
      <aside style={{
        width: 260, borderLeft: "1px solid var(--border)", background: "var(--bg-subtle)",
        display: "flex", flexDirection: "column", flexShrink: 0,
      }}>
        <div style={{ padding: "18px 16px", borderBottom: "1px solid var(--border)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", gap: 8 }}><div className="h-serif" style={{ fontSize: 18, fontWeight: 500 }}>Study Rooms</div></div>
          <CreateJoinBar onDone={load} />
          <button
            data-testid="social-directory-open"
            className="btn btn--sm"
            style={{ marginTop: 8, width: "100%" }}
            onClick={() => setTab("directory")}
          >
            <Icon name="users" size={12} /> Browse directory
          </button>
        </div>
        <FriendsPanel />
        <div style={{ flex: 1, overflowY: "auto", padding: 8 }}>
          {loading && <SocialRoomsSkeleton />}
          {!loading && rooms.length === 0 && (
            <div style={{ padding: 12, color: "var(--text-muted)", fontSize: 12 }}>
              No rooms yet — create or join one.
            </div>
          )}
          {!loading && rooms.map((r) => (
            <button
              key={r.id}
              data-testid={`social-room-item-${r.id}`}
              onClick={() => { setActiveId(r.id); setTab("chat"); }}
              style={{
                width: "100%", padding: "10px 12px",
                borderRadius: "var(--r-md)", textAlign: "left",
                background: activeId === r.id && tab !== "directory" ? "var(--bg-panel)" : "transparent",
                border: activeId === r.id && tab !== "directory" ? "1px solid var(--border)" : "1px solid transparent",
                marginBottom: 4, display: "flex", flexDirection: "column", gap: 2,
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 6 }}>
                {r.name}
                {r.is_public && <span className="chip" style={{ fontSize: 10 }}>Public</span>}
              </div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>
                {r.topic ? `${r.topic} · ` : ""}{r.member_count} members
              </div>
            </button>
          ))}
          {!loading && <PublicRoomsList excludeIds={rooms.map((r) => r.id)} onJoined={load} />}
        </div>
      </aside>
    </FullHeightScreen>
  );
}

function CopyChip({ code }: { code: string }) {
  const toast = useToast();
  const [copied, setCopied] = React.useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      toast.success("Invite code copied");
      setTimeout(() => setCopied(false), 2000);
    } catch {
      toast.error("Copy failed");
    }
  };
  return (
    <button data-testid="social-invite-copy" className="chip" onClick={copy} title="Copy invite code">
      {copied ? "Copied!" : code}
    </button>
  );
}

// CustomSelect import kept in case future branches use it
void CustomSelect;
