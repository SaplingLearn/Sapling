'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { supabase } from '@/lib/supabase';
import { getRoomMessages, sendRoomMessage } from '@/lib/api';
import Avatar from '@/components/Avatar';

interface Reaction {
  emoji: string;
  users: string[];
}

interface Message {
  id: string;
  userId: string;
  userName: string;
  text: string;
  imageUrl?: string;
  timestamp: Date;
  reactions: Reaction[];
}

interface Props {
  roomId: string;
  userId: string;
  members: { user_id: string; name: string }[];
}

// Avatar helpers moved to shared Avatar component

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

function dbRowToMessage(row: any): Message {
  return {
    id: row.id,
    userId: row.user_id,
    userName: row.user_name,
    text: row.text ?? '',
    imageUrl: row.image_url ?? undefined,
    timestamp: new Date(row.created_at),
    reactions: [],
  };
}

export default function RoomChat({ roomId, userId, members }: Props) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [input, setInput] = useState('');
  const [pendingImage, setPendingImage] = useState<string | null>(null);
  const [showEmojiPicker, setShowEmojiPicker] = useState(false);
  const [reactionPickerFor, setReactionPickerFor] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const pickerRef = useRef<HTMLDivElement>(null);

  // Load message history on mount / room change
  useEffect(() => {
    setMessages([]);
    setHistoryLoading(true);
    getRoomMessages(roomId).then(res => {
      setMessages(res.messages.map(dbRowToMessage));
    }).catch(console.error).finally(() => {
      setHistoryLoading(false);
    });
  }, [roomId]);

  // Subscribe to Realtime inserts
  useEffect(() => {
    const channel = supabase
      .channel(`room_messages:${roomId}`)
      .on(
        'postgres_changes',
        { event: 'INSERT', schema: 'public', table: 'room_messages', filter: `room_id=eq.${roomId}` },
        (payload) => {
          const msg = dbRowToMessage(payload.new);
          // Only add messages from others (own messages are added optimistically)
          if (msg.userId !== userId) {
            setMessages(prev => [...prev, msg]);
          }
        }
      )
      .subscribe();

    return () => { supabase.removeChannel(channel); };
  }, [roomId, userId]);

  // Scroll to bottom when messages change
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages]);

  // Close pickers on outside click
  useEffect(() => {
    function handleClick(e: MouseEvent) {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setShowEmojiPicker(false);
        setReactionPickerFor(null);
      }
    }
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, []);

  const myName = members.find(m => m.user_id === userId)?.name ?? 'You';

  async function sendMessage() {
    const text = input.trim();
    if (!text && !pendingImage) return;
    if (sending) return;

    // Optimistic update
    const tempId = `tmp_${Date.now()}`;
    const optimisticMsg: Message = {
      id: tempId,
      userId,
      userName: myName,
      text,
      imageUrl: pendingImage ?? undefined,
      timestamp: new Date(),
      reactions: [],
    };
    setMessages(prev => [...prev, optimisticMsg]);
    setInput('');
    setPendingImage(null);
    setShowEmojiPicker(false);

    setSending(true);
    try {
      await sendRoomMessage(roomId, userId, myName, text, pendingImage ?? undefined);
    } catch (e) {
      console.error('Failed to send message:', e);
      // Remove optimistic message on failure
      setMessages(prev => prev.filter(m => m.id !== tempId));
    } finally {
      setSending(false);
    }
  }

  function handleKeyDown(e: React.KeyboardEvent) {
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

  function toggleReaction(msgId: string, emoji: string) {
    setMessages(prev => prev.map(m => {
      if (m.id !== msgId) return m;
      const existing = m.reactions.find(r => r.emoji === emoji);
      if (existing) {
        const alreadyReacted = existing.users.includes(userId);
        return {
          ...m,
          reactions: alreadyReacted
            ? m.reactions.map(r => r.emoji === emoji
                ? { ...r, users: r.users.filter(u => u !== userId) }
                : r
              ).filter(r => r.users.length > 0)
            : m.reactions.map(r => r.emoji === emoji
                ? { ...r, users: [...r.users, userId] }
                : r
              ),
        };
      }
      return { ...m, reactions: [...m.reactions, { emoji, users: [userId] }] };
    }));
    setReactionPickerFor(null);
  }

  const isMine = useCallback((msg: Message) => msg.userId === userId, [userId]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', background: 'var(--bg-panel)' }}>

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

          return (
            <div
              key={msg.id}
              style={{
                display: 'flex',
                flexDirection: mine ? 'row-reverse' : 'row',
                alignItems: 'flex-end',
                gap: '8px',
                marginTop: showName ? '12px' : '2px',
              }}
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
                  style={{
                    position: 'relative',
                    background: mine ? 'var(--accent)' : 'var(--bg-subtle)',
                    border: mine ? 'none' : '1px solid var(--border-light)',
                    borderRadius: mine ? '16px 16px 4px 16px' : '16px 16px 16px 4px',
                    padding: msg.imageUrl && !msg.text ? '4px' : '9px 13px',
                    cursor: 'default',
                  }}
                  onMouseEnter={e => {
                    const btn = e.currentTarget.querySelector<HTMLButtonElement>('.react-btn');
                    if (btn) btn.style.opacity = '1';
                  }}
                  onMouseLeave={e => {
                    const btn = e.currentTarget.querySelector<HTMLButtonElement>('.react-btn');
                    if (btn) btn.style.opacity = '0';
                  }}
                >
                  {msg.imageUrl && (
                    <img
                      src={msg.imageUrl}
                      alt="shared"
                      style={{ maxWidth: '220px', maxHeight: '200px', borderRadius: '10px', display: 'block', marginBottom: msg.text ? '6px' : '0' }}
                    />
                  )}
                  {msg.text && (
                    <p style={{ margin: 0, fontSize: '13px', color: mine ? '#fff' : 'var(--text)', lineHeight: 1.45, whiteSpace: 'pre-wrap', wordBreak: 'break-word' }}>
                      {msg.text}
                    </p>
                  )}

                  {/* Reaction add button */}
                  <button
                    className="react-btn"
                    onClick={e => { e.stopPropagation(); setReactionPickerFor(reactionPickerFor === msg.id ? null : msg.id); setShowEmojiPicker(false); }}
                    style={{
                      position: 'absolute',
                      top: '-8px',
                      right: mine ? 'auto' : '-8px',
                      left: mine ? '-8px' : 'auto',
                      opacity: 0,
                      background: 'var(--bg-panel)',
                      border: '1px solid var(--border)',
                      borderRadius: '50%',
                      width: '22px',
                      height: '22px',
                      cursor: 'pointer',
                      fontSize: '12px',
                      display: 'flex',
                      alignItems: 'center',
                      justifyContent: 'center',
                      transition: 'opacity 120ms',
                      boxShadow: 'var(--shadow-sm)',
                    }}
                  >
                    😊
                  </button>
                </div>

                {/* Reactions */}
                {msg.reactions.length > 0 && (
                  <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                    {msg.reactions.map(r => (
                      <button
                        key={r.emoji}
                        onClick={() => toggleReaction(msg.id, r.emoji)}
                        title={`${r.users.length} reaction${r.users.length > 1 ? 's' : ''}`}
                        style={{
                          background: r.users.includes(userId) ? 'var(--accent-dim)' : 'var(--bg-subtle)',
                          border: `1px solid ${r.users.includes(userId) ? 'var(--accent-border)' : 'var(--border-light)'}`,
                          borderRadius: '10px',
                          padding: '1px 7px',
                          fontSize: '12px',
                          cursor: 'pointer',
                          display: 'flex',
                          alignItems: 'center',
                          gap: '3px',
                        }}
                      >
                        {r.emoji} <span style={{ fontSize: '10px', color: 'var(--text-muted)' }}>{r.users.length}</span>
                      </button>
                    ))}
                  </div>
                )}

                <span style={{ fontSize: '10px', color: 'var(--text-dim)' }}>{formatTime(msg.timestamp)}</span>
              </div>
            </div>
          );
        })}

        {/* Reaction picker floating */}
        {reactionPickerFor && (
          <div
            ref={pickerRef}
            style={{
              position: 'fixed',
              bottom: '90px',
              left: '50%',
              transform: 'translateX(-50%)',
              background: 'var(--bg-panel)',
              border: '1px solid var(--border-mid)',
              borderRadius: 'var(--radius-md)',
              padding: '8px',
              display: 'flex',
              flexWrap: 'wrap',
              gap: '4px',
              width: '260px',
              boxShadow: 'var(--shadow-md)',
              zIndex: 100,
            }}
          >
            {EMOJI_GRID.map(e => (
              <button
                key={e}
                onClick={() => toggleReaction(reactionPickerFor, e)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '18px', padding: '3px', borderRadius: '6px', transition: 'background var(--dur-fast)' }}
                onMouseEnter={ev => (ev.currentTarget.style.background = 'var(--bg-subtle)')}
                onMouseLeave={ev => (ev.currentTarget.style.background = 'none')}
              >
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
          <button
            onClick={() => setPendingImage(null)}
            style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '16px', color: 'var(--text-dim)' }}
          >
            ×
          </button>
        </div>
      )}

      {/* Input area */}
      <div style={{ borderTop: '1px solid var(--border-light)', padding: '12px 16px', background: 'var(--bg-panel)', position: 'relative' }}>

        {/* Emoji picker */}
        {showEmojiPicker && (
          <div
            ref={pickerRef}
            style={{
              position: 'absolute',
              bottom: '64px',
              left: '16px',
              background: 'var(--bg-panel)',
              border: '1px solid var(--border-mid)',
              borderRadius: 'var(--radius-md)',
              padding: '10px',
              display: 'flex',
              flexWrap: 'wrap',
              gap: '4px',
              width: '280px',
              boxShadow: 'var(--shadow-lg)',
              zIndex: 100,
            }}
          >
            {EMOJI_GRID.map(e => (
              <button
                key={e}
                onClick={() => { insertEmoji(e); setShowEmojiPicker(false); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '20px', padding: '4px', borderRadius: '6px', transition: 'background var(--dur-fast)' }}
                onMouseEnter={ev => (ev.currentTarget.style.background = 'var(--bg-subtle)')}
                onMouseLeave={ev => (ev.currentTarget.style.background = 'none')}
              >
                {e}
              </button>
            ))}
          </div>
        )}

        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '8px' }}>
          {/* Emoji button */}
          <button
            onClick={() => { setShowEmojiPicker(s => !s); setReactionPickerFor(null); }}
            title="Emoji"
            style={{
              background: showEmojiPicker ? 'var(--accent-dim)' : 'none',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              width: '34px',
              height: '34px',
              cursor: 'pointer',
              fontSize: '18px',
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background var(--dur-fast)',
            }}
          >
            😊
          </button>

          {/* Image button */}
          <button
            onClick={() => fileInputRef.current?.click()}
            title="Attach photo"
            style={{
              background: 'none',
              border: '1px solid var(--border)',
              borderRadius: 'var(--radius-sm)',
              width: '34px',
              height: '34px',
              cursor: 'pointer',
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              color: 'var(--text-muted)',
              fontSize: '15px',
              transition: 'background var(--dur-fast)',
            }}
            onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-subtle)')}
            onMouseLeave={e => (e.currentTarget.style.background = 'none')}
          >
            📷
          </button>
          <input ref={fileInputRef} type="file" accept="image/*" style={{ display: 'none' }} onChange={handleImageFile} />

          {/* Text input */}
          <textarea
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Message the group..."
            rows={1}
            style={{
              flex: 1,
              background: 'var(--bg-subtle)',
              border: '1px solid var(--border)',
              borderRadius: '18px',
              padding: '8px 14px',
              fontSize: '13px',
              color: 'var(--text)',
              resize: 'none',
              outline: 'none',
              fontFamily: 'inherit',
              lineHeight: 1.5,
              maxHeight: '100px',
              overflowY: 'auto',
              transition: 'border-color var(--dur-fast)',
            }}
            onFocus={e => (e.currentTarget.style.borderColor = 'var(--accent-border)')}
            onBlur={e => (e.currentTarget.style.borderColor = 'var(--border)')}
          />

          {/* Send button */}
          <button
            onClick={sendMessage}
            disabled={(!input.trim() && !pendingImage) || sending}
            style={{
              background: (input.trim() || pendingImage) && !sending ? 'var(--accent)' : 'var(--bg-subtle)',
              border: 'none',
              borderRadius: 'var(--radius-sm)',
              width: '34px',
              height: '34px',
              cursor: (input.trim() || pendingImage) && !sending ? 'pointer' : 'default',
              flexShrink: 0,
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              transition: 'background var(--dur-base)',
              color: (input.trim() || pendingImage) && !sending ? '#fff' : 'var(--text-dim)',
              fontSize: '16px',
            }}
          >
            ↑
          </button>
        </div>
      </div>
    </div>
  );
}
