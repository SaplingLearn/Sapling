'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { getRoomMessages, sendRoomMessage, deleteRoomMessage, editRoomMessage, toggleRoomReaction } from '@/lib/api';
import type { RoomMessageRow } from '@/lib/types';
import Avatar from '@/components/Avatar';

interface Reaction {
  emoji: string;
  userIds: string[];
}

interface ReplySnippet {
  id: string;
  userName: string;
  text: string | null;
}

interface Message {
  id: string;
  userId: string;
  userName: string;
  text: string;
  imageUrl?: string;
  timestamp: Date;
  reactions: Reaction[];
  replyToId: string | null;
  replyTo: ReplySnippet | null;
  isDeleted: boolean;
  editedAt: Date | null;
}

interface Props {
  roomId: string;
  userId: string;
  members: { user_id: string; name: string }[];
}

const EMOJI_GRID = [
  '😀','😂','😊','😍','🤔','😢','😅','🥳','😎','🤯',
  '😤','🫡','🤗','😬','🙃','😴','🥱','🫠','😇','🤓',
  '👍','👎','🙌','👏','💪','✌️','🫶','🤝','👀','🗣️',
  '❤️','🔥','⭐','✅','❌','💡','🎉','💯','🚀','⚡',
  '📚','📝','🎯','🏆','🌱','🌿','☀️','🌙','💧','🧠',
];

function formatTime(date: Date) {
  return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
}

function dbRowToMessage(row: RoomMessageRow): Message {
  return {
    id: row.id,
    userId: row.user_id,
    userName: row.user_name,
    text: row.text ?? '',
    imageUrl: row.image_url ?? undefined,
    timestamp: new Date(row.created_at),
    reactions: (row.reactions ?? []).map(r => ({ emoji: r.emoji, userIds: r.user_ids })),
    replyToId: row.reply_to_id ?? null,
    replyTo: row.reply_to ? { id: row.reply_to.id, userName: row.reply_to.user_name, text: row.reply_to.text } : null,
    isDeleted: row.is_deleted ?? false,
    editedAt: row.edited_at ? new Date(row.edited_at) : null,
  };
}

/** Render text with @Name mentions highlighted */
function renderText(text: string, memberNames: string[], isMine: boolean) {
  if (!memberNames.length) return <span>{text}</span>;
  const pattern = new RegExp(`(@(?:${memberNames.map(n => n.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|')}))`, 'g');
  const parts = text.split(pattern);
  return (
    <>
      {parts.map((part, i) =>
        pattern.test(part)
          ? <span key={i} style={{ color: isMine ? '#a7f3d0' : '#1a5c2a', fontWeight: 600 }}>{part}</span>
          : <span key={i}>{part}</span>
      )}
    </>
  );
}

export default function RoomChat({ roomId, userId, members }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [input, setInput] = useState('');
  const [pendingImage, setPendingImage] = useState<string | null>(null);
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [reactionPickerFor, setReactionPickerFor] = useState<string | null>(null);
  const [contextMenuFor, setContextMenuFor] = useState<string | null>(null);
  const [sending, setSending] = useState(false);

  // Reply / edit state
  const [replyingTo, setReplyingTo] = useState<Message | null>(null);
  const [editingMessage, setEditingMessage] = useState<Message | null>(null);

  // Typing indicators
  const [typingUsers, setTypingUsers] = useState<{ userId: string; userName: string }[]>([]);
  const typingTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const presenceChannelRef = useRef<ReturnType<typeof supabase.channel> | null>(null);

  // @mention autocomplete
  const [mentionQuery, setMentionQuery] = useState<string | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);
  const contextMenuRef = useRef<HTMLDivElement>(null);

  const memberNames = members.map(m => m.name);
  const myName = members.find(m => m.user_id === userId)?.name ?? 'You';

  // Load message history
  useEffect(() => {
    setMessages([]);
    setHistoryLoading(true);
    getRoomMessages(roomId).then(res => {
      setMessages(res.messages.map(dbRowToMessage));
    }).catch(console.error).finally(() => setHistoryLoading(false));
  }, [roomId]);

  // Realtime: messages INSERT/UPDATE + reactions INSERT/DELETE
  useEffect(() => {
    const channel = supabase
      .channel(`room_messages:${roomId}`)
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'room_messages', filter: `room_id=eq.${roomId}` }, (payload) => {
        const row = payload.new as RoomMessageRow;
        if (row.user_id === userId) return; // own messages added optimistically
        const msg = dbRowToMessage({ ...row, reactions: [], reply_to: null });
        // Resolve reply_to locally if possible
        if (row.reply_to_id) {
          setMessages(prev => {
            const replySource = prev.find(m => m.id === row.reply_to_id);
            return [...prev, {
              ...msg,
              replyTo: replySource ? { id: replySource.id, userName: replySource.userName, text: replySource.text } : null,
            }];
          });
        } else {
          setMessages(prev => [...prev, msg]);
        }
      })
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'room_messages', filter: `room_id=eq.${roomId}` }, (payload) => {
        const row = payload.new as RoomMessageRow;
        setMessages(prev => prev.map(m => m.id === row.id
          ? { ...m, text: row.text ?? '', isDeleted: row.is_deleted ?? false, editedAt: row.edited_at ? new Date(row.edited_at) : null }
          : m
        ));
      })
      .on('postgres_changes', { event: 'INSERT', schema: 'public', table: 'room_reactions' }, (payload) => {
        const r = payload.new as { message_id: string; user_id: string; emoji: string };
        setMessages(prev => prev.map(m => {
          if (m.id !== r.message_id) return m;
          const existing = m.reactions.find(rx => rx.emoji === r.emoji);
          if (existing) {
            if (existing.userIds.includes(r.user_id)) return m;
            return { ...m, reactions: m.reactions.map(rx => rx.emoji === r.emoji ? { ...rx, userIds: [...rx.userIds, r.user_id] } : rx) };
          }
          return { ...m, reactions: [...m.reactions, { emoji: r.emoji, userIds: [r.user_id] }] };
        }));
      })
      .on('postgres_changes', { event: 'DELETE', schema: 'public', table: 'room_reactions' }, (payload) => {
        const r = payload.old as { message_id: string; user_id: string; emoji: string };
        setMessages(prev => prev.map(m => {
          if (m.id !== r.message_id) return m;
          return {
            ...m,
            reactions: m.reactions
              .map(rx => rx.emoji === r.emoji ? { ...rx, userIds: rx.userIds.filter(u => u !== r.user_id) } : rx)
              .filter(rx => rx.userIds.length > 0),
          };
        }));
      })
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [roomId, userId]);

  // Presence channel for typing indicators
  useEffect(() => {
    const ch = supabase.channel(`presence:room:${roomId}`, { config: { presence: { key: userId } } });
    presenceChannelRef.current = ch;
    ch.on('presence', { event: 'sync' }, () => {
      const state = ch.presenceState<{ userId: string; userName: string; typing: boolean }>();
      const others = Object.values(state)
        .flat()
        .filter((p) => p.userId !== userId && p.typing);
      setTypingUsers(others);
    }).subscribe();
    return () => { supabase.removeChannel(ch); presenceChannelRef.current = null; };
  }, [roomId, userId]);

  // Scroll to bottom on new messages
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Close pickers/menus on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setShowEmojiPicker(false);
        setReactionPickerFor(null);
      }
      if (contextMenuRef.current && !contextMenuRef.current.contains(e.target as Node)) {
        setContextMenuFor(null);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  function broadcastTyping(isTyping: boolean) {
    presenceChannelRef.current?.track({ userId, userName: myName, typing: isTyping });
  }

  function handleInputChange(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const val = e.target.value;
    setInput(val);

    // Typing indicator
    broadcastTyping(true);
    if (typingTimeoutRef.current) clearTimeout(typingTimeoutRef.current);
    typingTimeoutRef.current = setTimeout(() => broadcastTyping(false), 3000);

    // @mention detection
    const cursor = e.target.selectionStart ?? val.length;
    const textBefore = val.slice(0, cursor);
    const mentionMatch = textBefore.match(/@(\w*)$/);
    if (mentionMatch) {
      setMentionQuery(mentionMatch[1].toLowerCase());
      setMentionIndex(0);
    } else {
      setMentionQuery(null);
    }
  }

  const filteredMembers = mentionQuery !== null
    ? members.filter(m => m.user_id !== userId && m.name.toLowerCase().startsWith(mentionQuery))
    : [];

  function insertMention(name: string) {
    const cursor = textareaRef.current?.selectionStart ?? input.length;
    const textBefore = input.slice(0, cursor);
    const textAfter = input.slice(cursor);
    const replaced = textBefore.replace(/@(\w*)$/, `@${name} `);
    setInput(replaced + textAfter);
    setMentionQuery(null);
    textareaRef.current?.focus();
  }

  async function sendMessage() {
    const text = input.trim();
    if (!text && !pendingImage) return;
    if (sending) return;

    if (editingMessage) {
      // Edit mode
      const msgId = editingMessage.id;
      const newText = text;
      setMessages(prev => prev.map(m => m.id === msgId ? { ...m, text: newText, editedAt: new Date() } : m));
      setEditingMessage(null);
      setInput('');
      broadcastTyping(false);
      try {
        await editRoomMessage(roomId, msgId, userId, newText);
      } catch (e) {
        console.error('Failed to edit message:', e);
      }
      return;
    }

    // Normal send
    const tempId = `tmp_${Date.now()}`;
    const replyTo = replyingTo ? { id: replyingTo.id, userName: replyingTo.userName, text: replyingTo.text } : null;
    const optimisticMsg: Message = {
      id: tempId,
      userId,
      userName: myName,
      text,
      imageUrl: pendingImage ?? undefined,
      timestamp: new Date(),
      reactions: [],
      replyToId: replyingTo?.id ?? null,
      replyTo,
      isDeleted: false,
      editedAt: null,
    };
    setMessages(prev => [...prev, optimisticMsg]);
    setInput('');
    setPendingImage(null);
    setShowEmojiPicker(false);
    setReplyingTo(null);
    broadcastTyping(false);

    setSending(true);
    try {
      await sendRoomMessage(roomId, userId, myName, text, pendingImage ?? undefined, replyingTo?.id);
    } catch (e) {
      console.error('Failed to send message:', e);
      setMessages(prev => prev.filter(m => m.id !== tempId));
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    // Handle mention navigation
    if (mentionQuery !== null && filteredMembers.length > 0) {
      if (e.key === 'ArrowDown') { e.preventDefault(); setMentionIndex(i => Math.min(i + 1, filteredMembers.length - 1)); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setMentionIndex(i => Math.max(i - 1, 0)); return; }
      if (e.key === 'Enter' || e.key === 'Tab') { e.preventDefault(); insertMention(filteredMembers[mentionIndex].name); return; }
      if (e.key === 'Escape') { setMentionQuery(null); return; }
    }
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  }

  function insertEmoji(emoji: string) {
    setInput(prev => prev + emoji);
  }

  function handleImageFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = ev => setPendingImage(ev.target?.result as string);
    reader.readAsDataURL(file);
    e.target.value = '';
  }

  async function handleToggleReaction(msgId: string, emoji: string) {
    // Optimistic
    setMessages(prev => prev.map(m => {
      if (m.id !== msgId) return m;
      const existing = m.reactions.find(r => r.emoji === emoji);
      if (existing) {
        const alreadyReacted = existing.userIds.includes(userId);
        return {
          ...m,
          reactions: alreadyReacted
            ? m.reactions.map(r => r.emoji === emoji ? { ...r, userIds: r.userIds.filter(u => u !== userId) } : r).filter(r => r.userIds.length > 0)
            : m.reactions.map(r => r.emoji === emoji ? { ...r, userIds: [...r.userIds, userId] } : r),
        };
      }
      return { ...m, reactions: [...m.reactions, { emoji, userIds: [userId] }] };
    }));
    setReactionPickerFor(null);
    try {
      await toggleRoomReaction(roomId, msgId, userId, emoji);
    } catch (e) {
      console.error('Failed to toggle reaction:', e);
    }
  }

  async function handleDeleteMessage(msgId: string) {
    setContextMenuFor(null);
    setMessages(prev => prev.map(m => m.id === msgId ? { ...m, isDeleted: true } : m));
    try {
      await deleteRoomMessage(roomId, msgId, userId);
    } catch (e) {
      console.error('Failed to delete message:', e);
      setMessages(prev => prev.map(m => m.id === msgId ? { ...m, isDeleted: false } : m));
    }
  }

  function handleStartEdit(msg: Message) {
    setContextMenuFor(null);
    setReplyingTo(null);
    setEditingMessage(msg);
    setInput(msg.text);
    textareaRef.current?.focus();
  }

  function cancelEdit() {
    setEditingMessage(null);
    setInput('');
  }

  const isMine = useCallback((msg: Message) => msg.userId === userId, [userId]);

  const typingLabel = typingUsers.length === 0
    ? null
    : typingUsers.length === 1
      ? `${typingUsers[0].userName} is typing...`
      : typingUsers.length === 2
        ? `${typingUsers[0].userName} and ${typingUsers[1].userName} are typing...`
        : 'Several people are typing...';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-panel)', position: 'relative' }}>

      {/* Messages area */}
      <div style={{ flex: 1, overflowY: 'auto', padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
        {!historyLoading && messages.length === 0 && (
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '10px', color: 'var(--text-dim)', paddingTop: '60px' }}>
            <span style={{ fontSize: '36px' }}>💬</span>
            <p style={{ fontSize: '14px', margin: 0 }}>No messages yet. Say hi!</p>
          </div>
        )}

        {messages.map((msg, i) => {
          const mine = isMine(msg);
          const showAvatar = !mine && (i === 0 || messages[i - 1].userId !== msg.userId);
          const showName = !mine && showAvatar;
          const next = messages[i + 1];
          const showTimestamp = !next || next.userId !== msg.userId || (next.timestamp.getTime() - msg.timestamp.getTime()) > 5 * 60 * 1000;

          if (msg.isDeleted) {
            return (
              <div key={msg.id} style={{ display: 'flex', flexDirection: mine ? 'row-reverse' : 'row', alignItems: 'flex-end', gap: '8px', marginTop: showName ? '12px' : '2px' }}>
                {!mine && <div style={{ width: 30, flexShrink: 0 }} />}
                <p style={{ margin: 0, fontSize: '12px', color: 'var(--text-dim)', fontStyle: 'italic' }}>Message deleted</p>
              </div>
            );
          }

          return (
            <div
              key={msg.id}
              style={{ display: 'flex', flexDirection: mine ? 'row-reverse' : 'row', alignItems: 'flex-end', gap: '8px', marginTop: showName ? '12px' : '2px' }}
            >
              {/* Avatar (others only) */}
              {!mine && (
                showAvatar
                  ? <Avatar userId={msg.userId} name={msg.userName} size={30} />
                  : <div style={{ width: 30, height: 30, flexShrink: 0 }} />
              )}

              <div style={{ maxWidth: '65%', display: 'flex', flexDirection: 'column', alignItems: mine ? 'flex-end' : 'flex-start', gap: '3px' }}>
                {showName && (
                  <span style={{ fontSize: '11px', color: 'var(--text-dim)', paddingLeft: '2px' }}>{msg.userName}</span>
                )}

                {/* Bubble */}
                <div
                  style={{ position: 'relative', background: mine ? 'var(--accent)' : 'var(--bg-subtle)', border: mine ? 'none' : '1px solid var(--border-light)', borderRadius: mine ? '16px 16px 4px 16px' : '16px 16px 16px 4px', padding: msg.imageUrl && !msg.text ? '4px' : '9px 13px', cursor: 'default' }}
                  onMouseEnter={e => {
                    e.currentTarget.querySelectorAll<HTMLElement>('.msg-action').forEach(el => el.style.opacity = '1');
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.querySelectorAll<HTMLElement>('.msg-action').forEach(el => el.style.opacity = '0');
                  }}
                >
                  {/* Reply quote */}
                  {msg.replyTo && (
                    <div style={{ borderLeft: '2px solid', borderColor: mine ? 'rgba(255,255,255,0.4)' : 'var(--accent-border)', paddingLeft: '8px', marginBottom: '6px', opacity: 0.75 }}>
                      <span style={{ display: 'block', fontSize: '10px', fontWeight: 600, color: mine ? 'rgba(255,255,255,0.8)' : 'var(--accent)', marginBottom: '1px' }}>{msg.replyTo.userName}</span>
                      <span style={{ fontSize: '11px', color: mine ? 'rgba(255,255,255,0.7)' : 'var(--text-muted)', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical', overflow: 'hidden' }}>
                        {msg.replyTo.text ?? 'Message deleted'}
                      </span>
                    </div>
                  )}

                  {msg.imageUrl && (
                    <img src={msg.imageUrl} alt="shared" style={{ maxWidth: '220px', maxHeight: '200px', borderRadius: '10px', display: 'block', marginBottom: msg.text ? '6px' : '0' }} />
                  )}
                  {msg.text && (
                    <p style={{ margin: 0, fontSize: '13px', color: mine ? '#fff' : 'var(--text)', lineHeight: 1.45, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {renderText(msg.text, memberNames, mine)}
                    </p>
                  )}

                  {/* Action buttons (hover) */}
                  <div style={{ position: 'absolute', top: '-10px', [mine ? 'left' : 'right']: '-4px', display: 'flex', gap: '2px', zIndex: 10 }}>
                    {/* Reply button */}
                    <button
                      className="msg-action"
                      onClick={e => { e.stopPropagation(); setReplyingTo(msg); setEditingMessage(null); textareaRef.current?.focus(); }}
                      title="Reply"
                      style={{ opacity: 0, background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '50%', width: '22px', height: '22px', cursor: 'pointer', fontSize: '11px', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'opacity 120ms', boxShadow: 'var(--shadow-sm)' }}
                    >
                      ↩
                    </button>
                    {/* Reaction button */}
                    <button
                      className="msg-action"
                      onClick={e => { e.stopPropagation(); setReactionPickerFor(reactionPickerFor === msg.id ? null : msg.id); setShowEmojiPicker(false); setContextMenuFor(null); }}
                      style={{ opacity: 0, background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '50%', width: '22px', height: '22px', cursor: 'pointer', fontSize: '12px', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'opacity 120ms', boxShadow: 'var(--shadow-sm)' }}
                    >
                      😊
                    </button>
                    {/* Context menu (own messages only) */}
                    {mine && (
                      <div style={{ position: 'relative' }}>
                        <button
                          className="msg-action"
                          onClick={e => { e.stopPropagation(); setContextMenuFor(contextMenuFor === msg.id ? null : msg.id); setReactionPickerFor(null); setShowEmojiPicker(false); }}
                          style={{ opacity: 0, background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: '50%', width: '22px', height: '22px', cursor: 'pointer', fontSize: '13px', display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'opacity 120ms', boxShadow: 'var(--shadow-sm)', fontWeight: 700, color: 'var(--text-muted)' }}
                        >
                          ···
                        </button>
                        {contextMenuFor === msg.id && (
                          <div
                            ref={contextMenuRef}
                            style={{ position: 'absolute', top: '26px', [mine ? 'right' : 'left']: '0', background: 'var(--bg-panel)', border: '1px solid var(--border-mid)', borderRadius: '8px', boxShadow: 'var(--shadow-md)', minWidth: '110px', zIndex: 200, overflow: 'hidden' }}
                          >
                            <button
                              onClick={() => handleStartEdit(msg)}
                              style={{ display: 'block', width: '100%', padding: '8px 12px', background: 'none', border: 'none', textAlign: 'left', fontSize: '12px', color: 'var(--text)', cursor: 'pointer', fontFamily: 'inherit' }}
                              onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-subtle)')}
                              onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                            >
                              Edit
                            </button>
                            <button
                              onClick={() => handleDeleteMessage(msg.id)}
                              style={{ display: 'block', width: '100%', padding: '8px 12px', background: 'none', border: 'none', textAlign: 'left', fontSize: '12px', color: '#dc2626', cursor: 'pointer', fontFamily: 'inherit' }}
                              onMouseEnter={e => (e.currentTarget.style.background = '#fef2f2')}
                              onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                            >
                              Delete
                            </button>
                          </div>
                        )}
                      </div>
                    )}
                  </div>
                </div>

                {/* Reactions */}
                {msg.reactions.length > 0 && (
                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                    {msg.reactions.map(r => (
                      <button
                        key={r.emoji}
                        onClick={() => handleToggleReaction(msg.id, r.emoji)}
                        title={`${r.userIds.length} reaction${r.userIds.length > 1 ? 's' : ''}`}
                        style={{ background: r.userIds.includes(userId) ? 'var(--accent-dim)' : 'var(--bg-subtle)', border: `1px solid ${r.userIds.includes(userId) ? 'var(--accent-border)' : 'var(--border-light)'}`, borderRadius: '10px', padding: '1px 7px', fontSize: '12px', cursor: 'pointer', display: 'flex', alignItems: 'center', gap: '3px' }}
                      >
                        {r.emoji} <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{r.userIds.length}</span>
                      </button>
                    ))}
                  </div>
                )}

                {showTimestamp && (
                  <span style={{ fontSize: '10px', color: 'var(--text-dim)' }}>
                    {formatTime(msg.timestamp)}
                    {msg.editedAt && <span style={{ marginLeft: '4px', opacity: 0.7 }}>(edited)</span>}
                  </span>
                )}
              </div>
            </div>
          );
        })}

        {/* Reaction picker */}
        {reactionPickerFor && (
          <div ref={pickerRef} style={{ position: 'fixed', bottom: '90px', left: '50%', transform: 'translateX(-50%)', background: 'var(--bg-panel)', border: '1px solid var(--border-mid)', borderRadius: 'var(--radius-md)', padding: '8px', display: 'flex', flexWrap: 'wrap', gap: '4px', width: '260px', boxShadow: 'var(--shadow-md)', zIndex: 100 }}>
            {EMOJI_GRID.map(e => (
              <button key={e} onClick={() => handleToggleReaction(reactionPickerFor, e)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '18px', padding: '3px', borderRadius: '6px' }} onMouseEnter={ev => (ev.currentTarget.style.background = 'var(--bg-subtle)')} onMouseLeave={ev => (ev.currentTarget.style.background = 'none')}>
                {e}
              </button>
            ))}
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      {/* Pending image preview */}
      {pendingImage && (
        <div style={{ padding: '8px 20px 0', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <img src={pendingImage} alt="preview" style={{ height: '56px', borderRadius: '8px', border: '1px solid var(--border)' }} />
          <button onClick={() => setPendingImage(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '16px', color: 'var(--text-dim)' }}>×</button>
        </div>
      )}

      {/* Input area */}
      <div style={{ borderTop: '1px solid var(--border-light)', padding: '12px 16px', background: 'var(--bg-panel)', position: 'relative' }}>

        {/* Typing indicator */}
        {typingLabel && (
          <div style={{ fontSize: '11px', color: 'var(--text-dim)', fontStyle: 'italic', marginBottom: '6px', paddingLeft: '2px' }}>
            {typingLabel}
          </div>
        )}

        {/* Edit mode banner */}
        {editingMessage && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(245,158,11,0.08)', border: '1px solid rgba(245,158,11,0.25)', borderRadius: '8px', padding: '5px 10px', marginBottom: '8px' }}>
            <span style={{ fontSize: '11px', color: '#92400e' }}>
              <strong>Editing:</strong> <span style={{ opacity: 0.8 }}>{editingMessage.text.slice(0, 60)}{editingMessage.text.length > 60 ? '…' : ''}</span>
            </span>
            <button onClick={cancelEdit} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '14px', color: '#92400e', lineHeight: 1, padding: '0 2px' }}>×</button>
          </div>
        )}

        {/* Reply preview */}
        {replyingTo && !editingMessage && (
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'var(--bg-subtle)', border: '1px solid var(--border-light)', borderLeft: '3px solid var(--accent-border)', borderRadius: '0 8px 8px 0', padding: '5px 10px', marginBottom: '8px' }}>
            <div>
              <span style={{ display: 'block', fontSize: '10px', fontWeight: 600, color: 'var(--accent)', marginBottom: '1px' }}>{replyingTo.userName}</span>
              <span style={{ fontSize: '11px', color: 'var(--text-muted)' }}>{replyingTo.text.slice(0, 80)}{replyingTo.text.length > 80 ? '…' : ''}</span>
            </div>
            <button onClick={() => setReplyingTo(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '14px', color: 'var(--text-dim)', lineHeight: 1, padding: '0 2px' }}>×</button>
          </div>
        )}

        {/* @mention dropdown */}
        {mentionQuery !== null && filteredMembers.length > 0 && (
          <div style={{ position: 'absolute', bottom: '100%', left: '16px', background: 'var(--bg-panel)', border: '1px solid var(--border-mid)', borderRadius: '8px', boxShadow: 'var(--shadow-md)', minWidth: '180px', zIndex: 200, overflow: 'hidden', marginBottom: '4px' }}>
            {filteredMembers.map((m, i) => (
              <button
                key={m.user_id}
                onMouseDown={e => { e.preventDefault(); insertMention(m.name); }}
                style={{ display: 'flex', alignItems: 'center', gap: '8px', width: '100%', padding: '7px 12px', background: i === mentionIndex ? 'var(--bg-subtle)' : 'none', border: 'none', cursor: 'pointer', fontFamily: 'inherit', fontSize: '13px', color: 'var(--text)', textAlign: 'left' }}
                onMouseEnter={() => setMentionIndex(i)}
              >
                <Avatar userId={m.user_id} name={m.name} size={20} />
                <span>{m.name}</span>
              </button>
            ))}
          </div>
        )}

        {/* Emoji picker for input */}
        {showEmojiPicker && (
          <div ref={pickerRef} style={{ position: 'absolute', bottom: '64px', left: '16px', background: 'var(--bg-panel)', border: '1px solid var(--border-mid)', borderRadius: 'var(--radius-md)', padding: '10px', display: 'flex', flexWrap: 'wrap', gap: '4px', width: '280px', boxShadow: 'var(--shadow-lg)', zIndex: 100 }}>
            {EMOJI_GRID.map(e => (
              <button key={e} onClick={() => { insertEmoji(e); setShowEmojiPicker(false); }} style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '20px', padding: '4px', borderRadius: '6px' }} onMouseEnter={ev => (ev.currentTarget.style.background = 'var(--bg-subtle)')} onMouseLeave={ev => (ev.currentTarget.style.background = 'none')}>
                {e}
              </button>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '8px' }}>
          <button
            onClick={() => { setShowEmojiPicker(s => !s); setReactionPickerFor(null); }}
            title="Emoji"
            style={{ background: showEmojiPicker ? 'var(--accent-dim)' : 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', width: '34px', height: '34px', cursor: 'pointer', fontSize: '18px', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'background var(--dur-fast)' }}
          >
            😊
          </button>

          <button
            onClick={() => fileInputRef.current?.click()}
            title="Attach photo"
            style={{ background: 'none', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', width: '34px', height: '34px', cursor: 'pointer', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: '15px' }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-subtle)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'none')}
          >
            📷
          </button>
          <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleImageFile} />

          <textarea
            ref={textareaRef}
            value={input}
            onChange={handleInputChange}
            onKeyDown={handleKeyDown}
            placeholder={editingMessage ? 'Edit message...' : 'Message the group...'}
            rows={1}
            style={{ flex: 1, background: editingMessage ? 'rgba(245,158,11,0.06)' : 'var(--bg-subtle)', border: `1px solid ${editingMessage ? 'rgba(245,158,11,0.4)' : 'var(--border)'}`, borderRadius: '18px', padding: '8px 14px', fontSize: '13px', color: 'var(--text)', resize: 'none', outline: 'none', fontFamily: 'inherit', lineHeight: 1.5, maxHeight: '100px', overflowY: 'auto', transition: 'border-color var(--dur-fast)' }}
            onFocus={e => { if (!editingMessage) e.currentTarget.style.borderColor = 'var(--accent-border)'; }}
            onBlur={e => { if (!editingMessage) e.currentTarget.style.borderColor = 'var(--border)'; }}
          />

          <button
            onClick={sendMessage}
            disabled={(!input.trim() && !pendingImage) || sending}
            style={{ background: (input.trim() || pendingImage) && !sending ? 'var(--accent)' : 'var(--bg-subtle)', border: 'none', borderRadius: 'var(--radius-sm)', width: '34px', height: '34px', cursor: (input.trim() || pendingImage) && !sending ? 'pointer' : 'default', flexShrink: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', transition: 'background var(--dur-base)', color: (input.trim() || pendingImage) && !sending ? '#fff' : 'var(--text-dim)', fontSize: '16px' }}
          >
            {editingMessage ? '✓' : '↑'}
          </button>
        </div>
      </div>
    </div>
  );
}
