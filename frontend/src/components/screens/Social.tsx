"use client";
import React from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Icon } from "../Icon";
import { Avatar } from "../Avatar";
import { CustomSelect } from "../CustomSelect";
import { SocialRoomsSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useUser } from "@/context/UserContext";
import { IS_LOCAL_MODE } from "@/lib/api";
import {
  getUserRooms,
  createRoom,
  joinRoom,
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
  type StudentRow,
} from "@/lib/api";
import type { RoomMessageRow, RoomOverviewData } from "@/lib/types";

type Tab = "overview" | "chat" | "match" | "activity" | "directory";
type Room = { id: string; name: string; invite_code: string; member_count: number; created_by?: string };

const EMOJI_50 = [
  "👍","🎉","❤️","🔥","🙌","💯","😂","😊","🤔","😮",
  "😢","🙏","👀","💡","✅","⚠️","🚀","🌱","📚","🧠",
  "⭐","✨","👏","💪","🎯","💬","☕","🍀","🌟","⚡",
  "🤝","✏️","📝","🧪","🔬","🎓","📊","🧩","🌈","🌻",
  "🥳","😎","🤷","🤯","🫡","🙈","🔖","📌","💭","💫",
];

function supabaseClient() {
  if (IS_LOCAL_MODE) return null;
  if (typeof window === "undefined") return null;
  try {
    // Lazy so local mode doesn't blow up.
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { getSupabase } = require("@/lib/supabase");
    return getSupabase();
  } catch {
    return null;
  }
}

function CreateJoinBar({ onDone }: { onDone: () => void }) {
  const { userId } = useUser();
  const toast = useToast();
  const [mode, setMode] = React.useState<"idle" | "create" | "join">("idle");
  const [value, setValue] = React.useState("");

  const submit = async () => {
    if (!value.trim() || !userId) return;
    try {
      if (mode === "create") await createRoom(userId, value.trim());
      else if (mode === "join") await joinRoom(userId, value.trim());
      toast.success(mode === "create" ? "Room created" : "Joined room");
      setMode("idle");
      setValue("");
      onDone();
    } catch (err) {
      toast.error(String(err));
    }
  };

  if (mode === "idle") {
    return (
      <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
        <button className="btn btn--sm btn--primary" style={{ flex: 1 }} onClick={() => setMode("create")}>
          <Icon name="plus" size={12} /> Create
        </button>
        <button className="btn btn--sm" style={{ flex: 1 }} onClick={() => setMode("join")}>Join</button>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
      <input
        autoFocus
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") submit(); if (e.key === "Escape") setMode("idle"); }}
        placeholder={mode === "create" ? "Room name" : "Invite code"}
        style={{
          flex: 1, padding: "6px 10px",
          border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
          fontSize: 12, background: "var(--bg-panel)",
        }}
      />
      <button className="btn btn--sm btn--primary" onClick={submit}>Go</button>
    </div>
  );
}

function RoomChat({ roomId, members }: { roomId: string; members: { user_id: string; name: string }[] }) {
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

  // Realtime subscriptions.
  React.useEffect(() => {
    const supa = supabaseClient();
    if (!supa) return;

    const channel = supa
      .channel(`room:${roomId}`)
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "room_messages", filter: `room_id=eq.${roomId}` },
        (payload: any) => {
          const row = payload.new as RoomMessageRow;
          setMessages(prev => {
            const withoutTmp = prev.filter(m => !m.id.startsWith("tmp_") || m.text !== row.text || m.user_id !== row.user_id);
            if (withoutTmp.some(m => m.id === row.id)) return withoutTmp;
            return [...withoutTmp, { ...row, reactions: [], reply_to: null }];
          });
        })
      .on("postgres_changes",
        { event: "UPDATE", schema: "public", table: "room_messages", filter: `room_id=eq.${roomId}` },
        (payload: any) => {
          const row = payload.new as RoomMessageRow;
          setMessages(prev => prev.map(m => m.id === row.id ? { ...m, ...row } : m));
        })
      .on("postgres_changes",
        { event: "INSERT", schema: "public", table: "room_reactions" },
        () => { void load(); })
      .on("postgres_changes",
        { event: "DELETE", schema: "public", table: "room_reactions" },
        () => { void load(); })
      .subscribe();

    return () => { supa.removeChannel(channel); };
  }, [roomId, load]);

  // Presence / typing channel.
  React.useEffect(() => {
    const supa = supabaseClient();
    if (!supa || !userId) return;
    const ch = supa.channel(`presence:${roomId}`, { config: { presence: { key: userId } } });
    ch
      .on("presence", { event: "sync" }, () => {
        const state = ch.presenceState();
        const typers = new Set<string>();
        Object.entries(state).forEach(([uid, arr]: [string, any]) => {
          if (uid === userId) return;
          const p = arr?.[0];
          if (p?.typing && Date.now() - (p.last || 0) < 3000) typers.add(p.name || uid);
        });
        setTypingUsers(typers);
      })
      .subscribe(async (status: string) => {
        if (status === "SUBSCRIBED") {
          await ch.track({ name: userName || "Anonymous", typing: false, last: Date.now() });
        }
      });
    typingChannelRef.current = ch;
    return () => {
      ch.unsubscribe();
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
      await sendRoomMessage(roomId, userId, userName || "Me", text, undefined, r?.id);
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
      await toggleRoomReaction(roomId, messageId, userId, emoji);
      void load();
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
      const path = `${roomId}/${userId}-${Date.now()}-${file.name}`;
      const up = await supa.storage.from("chat-images").upload(path, file);
      if (up.error) throw up.error;
      const pub = supa.storage.from("chat-images").getPublicUrl(path);
      const url: string = pub.data.publicUrl;
      await sendRoomMessage(roomId, userId, userName || "Me", "", url);
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
      <div style={{ padding: "6px 20px 0", fontSize: 11, color: "var(--text-muted)", minHeight: 18 }}>
        {typingUsers.size > 0 && `${Array.from(typingUsers).join(", ")} typing…`}
      </div>
      <div
        ref={scrollRef}
        style={{ flex: 1, overflowY: "auto", padding: "12px 24px", display: "flex", flexDirection: "column", gap: 14 }}
      >
        {hasMore && (
          <div style={{ textAlign: "center" }}>
            <button className="btn btn--ghost btn--sm" onClick={loadEarlier} disabled={loadingEarlier}>
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
            <div key={m.id} style={{ display: "flex", gap: 10, alignSelf: self ? "flex-end" : "flex-start", maxWidth: "72%", position: "relative" }} className="fade-in">
              {!self && <Avatar name={m.user_name} size={32} />}
              <div style={{ position: "relative" }}>
                {!self && <div style={{ fontSize: 11, color: "var(--text-dim)", fontWeight: 600, marginBottom: 2 }}>{m.user_name}</div>}
                {m.reply_to && (
                  <div style={{ fontSize: 11, color: "var(--text-muted)", borderLeft: "2px solid var(--accent)", paddingLeft: 6, marginBottom: 4 }}>
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
                    <button className="btn btn--sm btn--primary" onClick={() => handleEditSave(m.id)}>Save</button>
                    <button className="btn btn--sm btn--ghost" onClick={() => { setEditing(null); setEditValue(""); }}>
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
                      <img src={m.image_url} alt="attachment" style={{ maxWidth: 260, borderRadius: "var(--r-sm)", marginBottom: m.text ? 6 : 0 }} />
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
                    <button className="btn btn--ghost btn--sm" title="React" onClick={(e) => { e.stopPropagation(); setPicker(m.id); }}>
                      😊
                    </button>
                    <button className="btn btn--ghost btn--sm" title="Reply" onClick={(e) => { e.stopPropagation(); setReplyTo(m); setMenu(null); inputRef.current?.focus(); }}>
                      ↪
                    </button>
                    {self && (
                      <>
                        <button className="btn btn--ghost btn--sm" title="Edit" onClick={(e) => { e.stopPropagation(); setEditing(m.id); setEditValue(m.text || ""); setMenu(null); }}>
                          <Icon name="pencil" size={11} />
                        </button>
                        <button className="btn btn--ghost btn--sm" title="Delete" onClick={(e) => { e.stopPropagation(); handleDelete(m); setMenu(null); }}>
                          <Icon name="x" size={11} />
                        </button>
                      </>
                    )}
                  </div>
                )}
                {picker === m.id && (
                  <div style={{ position: "absolute", top: 20, right: 0, zIndex: 20, background: "var(--bg-panel)", border: "1px solid var(--border-strong)", borderRadius: "var(--r-md)", padding: 10, boxShadow: "var(--shadow-lg)", display: "grid", gridTemplateColumns: "repeat(10, 1fr)", gap: 4, width: 340 }}>
                    {EMOJI_50.map((e) => (
                      <button key={e} onClick={() => handleReaction(m.id, e)} style={{ fontSize: 16, padding: 4, borderRadius: 4 }}>{e}</button>
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
          <button className="btn btn--ghost btn--sm" onClick={() => setReplyTo(null)}>
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
              flex: 1, border: 0, background: "transparent", outline: "none",
              fontSize: 14, padding: "6px 0", resize: "none", fontFamily: "inherit", color: "inherit",
            }}
          />
          <input
            ref={fileRef}
            type="file"
            accept="image/*"
            hidden
            onChange={e => {
              const f = e.target.files?.[0];
              if (f) handleImage(f);
              e.target.value = "";
            }}
          />
          <button className="btn btn--ghost btn--sm" onClick={() => fileRef.current?.click()} title="Attach image">
            <Icon name="doc" size={13} />
          </button>
          <button className="btn btn--primary btn--sm" onClick={send} disabled={!input.trim()}>
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
  const isLeader = data?.room?.created_by === userId;

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
            isLeader={data.room.created_by === m.user_id}
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
    <div style={{
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
          <button className="btn btn--primary" onClick={run} disabled={loading}>
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
      s.courses.some(c => c.toLowerCase().includes(t)) ||
      s.top_concepts.some(c => c.toLowerCase().includes(t))
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
                  {s.top_concepts.length > 0 && (
                    <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 6 }}>
                      {s.top_concepts.slice(0, 3).map(c => (
                        <span key={c} className="chip chip--accent">{c}</span>
                      ))}
                    </div>
                  )}
                  <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 6 }}>
                    {s.stats.mastered}/{s.stats.total} concepts · {s.streak}d streak
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
      setActiveId(prev => prev || list[0]?.id || null);
    } catch (err) {
      console.error("rooms load failed", err);
    } finally {
      setLoading(false);
    }
  }, [userId]);

  React.useEffect(() => { if (userReady && userId) load(); }, [userReady, userId, load]);

  React.useEffect(() => {
    if (!activeId) { setOverview(null); return; }
    getRoomOverview(activeId).then(setOverview).catch(console.error);
  }, [activeId]);

  const active = rooms.find((r) => r.id === activeId);
  const members = (overview?.members || []).map(m => ({ user_id: m.user_id, name: m.name }));

  return (
    <div style={{ display: "flex", height: "100vh" }}>
      <div style={{ flex: 1, display: "flex", flexDirection: "column", minWidth: 0 }}>
        {tab === "directory" ? <SchoolDirectory /> : active ? (
          <>
            <div style={{ padding: "18px 24px", borderBottom: "1px solid var(--border)", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
              <div>
                <div className="h-serif" style={{ fontSize: 22, fontWeight: 500 }}>{active.name}</div>
                <div style={{ fontSize: 11, color: "var(--text-muted)", display: "flex", alignItems: "center", gap: 8, marginTop: 2 }}>
                  <CopyChip code={active.invite_code} />
                  <span>{active.member_count} members</span>
                </div>
              </div>
              <div style={{ display: "flex", gap: 6 }}>
                {(["overview", "chat", "match", "activity"] as Tab[]).map((t) => (
                  <button
                    key={t}
                    onClick={() => setTab(t)}
                    style={{
                      padding: "6px 14px", fontSize: 12, fontWeight: 500,
                      borderRadius: "var(--r-sm)",
                      background: tab === t ? "var(--accent-soft)" : "transparent",
                      color: tab === t ? "var(--accent)" : "var(--text-dim)",
                      textTransform: "capitalize",
                    }}
                  >
                    {t === "match" ? "Study match" : t}
                  </button>
                ))}
              </div>
            </div>
            {tab === "chat" && <RoomChat roomId={active.id} members={members} />}
            {tab === "overview" && <RoomOverview roomId={active.id} onChange={load} />}
            {tab === "match" && <StudyMatch roomId={active.id} />}
            {tab === "activity" && <RoomActivity roomId={active.id} />}
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
          <div className="h-serif" style={{ fontSize: 18, fontWeight: 500 }}>Study Rooms</div>
          <CreateJoinBar onDone={load} />
          <button
            className="btn btn--sm"
            style={{ marginTop: 8, width: "100%" }}
            onClick={() => setTab("directory")}
          >
            <Icon name="users" size={12} /> Browse directory
          </button>
        </div>
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
              onClick={() => { setActiveId(r.id); setTab("chat"); }}
              style={{
                width: "100%", padding: "10px 12px",
                borderRadius: "var(--r-md)", textAlign: "left",
                background: activeId === r.id && tab !== "directory" ? "var(--bg-panel)" : "transparent",
                border: activeId === r.id && tab !== "directory" ? "1px solid var(--border)" : "1px solid transparent",
                marginBottom: 4, display: "flex", flexDirection: "column", gap: 2,
              }}
            >
              <div style={{ fontSize: 13, fontWeight: 600 }}>{r.name}</div>
              <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{r.member_count} members</div>
            </button>
          ))}
        </div>
      </aside>
    </div>
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
    <button className="chip" onClick={copy} title="Copy invite code">
      {copied ? "Copied!" : code}
    </button>
  );
}

// CustomSelect import kept in case future branches use it
void CustomSelect;
