'use client';

import { useState } from 'react';
import { kickMember, leaveRoom } from '@/lib/api';
import { useUser } from '@/context/UserContext';
import Avatar from '@/components/Avatar';

interface Member {
  user_id: string;
  name: string;
}

interface Props {
  roomId: string;
  roomName: string;
  leaderId: string;
  members: Member[];
  currentUserId: string;
  onLeave: () => void;
  onMembersChange: (members: Member[]) => void;
}

export default function RoomMembers({ roomId, roomName, leaderId, members, currentUserId, onLeave, onMembersChange }: Props) {
  const { avatarUrl } = useUser();
  const [confirmLeave, setConfirmLeave] = useState(false);
  const [kickingId, setKickingId] = useState<string | null>(null);
  const [leavingLoading, setLeavingLoading] = useState(false);

  const isLeader = currentUserId === leaderId;

  async function handleKick(memberId: string) {
    setKickingId(memberId);
    try {
      await kickMember(roomId, memberId, currentUserId);
      onMembersChange(members.filter(m => m.user_id !== memberId));
    } catch (e) {
      console.error(e);
    } finally {
      setKickingId(null);
    }
  }

  async function handleLeave() {
    setLeavingLoading(true);
    try {
      await leaveRoom(roomId, currentUserId);
      onLeave();
    } catch (e) {
      console.error(e);
      setLeavingLoading(false);
    }
  }

  return (
    <div style={{ padding: '28px 24px', maxWidth: '520px' }}>
      <h2 style={{ fontSize: '15px', fontWeight: 600, color: 'var(--text)', margin: '0 0 20px' }}>
        Members
        <span style={{ fontSize: '13px', fontWeight: 400, color: 'var(--text-dim)', marginLeft: '6px' }}>
          {members.length}
        </span>
      </h2>

      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '28px' }}>
        {members.map(m => {
          const isMe = m.user_id === currentUserId;
          const isThisLeader = m.user_id === leaderId;

          return (
            <div
              key={m.user_id}
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '12px',
                padding: '10px 12px',
                borderRadius: 'var(--radius-md)',
                background: isMe ? 'var(--accent-dim)' : 'transparent',
                border: `1px solid ${isMe ? 'var(--accent-border)' : 'transparent'}`,
                transition: 'background var(--dur-fast)',
              }}
            >
              {/* Avatar */}
              <Avatar
                userId={m.user_id}
                name={m.name}
                size={36}
                avatarUrl={isMe ? avatarUrl : undefined}
              />

              {/* Name + badges */}
              <div style={{ flex: 1, display: 'flex', alignItems: 'center', gap: '7px', minWidth: 0 }}>
                <span style={{ fontSize: '14px', fontWeight: 500, color: 'var(--text)', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {m.name}
                </span>
                {isThisLeader && (
                  <span style={{
                    fontSize: '10px',
                    fontWeight: 700,
                    color: '#92400e',
                    background: '#fef3c7',
                    border: '1px solid #fcd34d',
                    borderRadius: '4px',
                    padding: '1px 6px',
                    letterSpacing: '0.04em',
                    flexShrink: 0,
                  }}>
                    LEADER
                  </span>
                )}
                {isMe && (
                  <span style={{ fontSize: '11px', color: 'var(--text-dim)', flexShrink: 0 }}>you</span>
                )}
              </div>

              {/* Kick button — only leader sees it, not on themselves or other leaders */}
              {isLeader && !isMe && (
                <button
                  onClick={() => handleKick(m.user_id)}
                  disabled={kickingId === m.user_id}
                  style={{
                    background: 'none',
                    border: '1px solid rgba(220,38,38,0.3)',
                    borderRadius: 'var(--radius-sm)',
                    padding: '4px 12px',
                    fontSize: '12px',
                    color: '#dc2626',
                    cursor: kickingId === m.user_id ? 'default' : 'pointer',
                    flexShrink: 0,
                    opacity: kickingId === m.user_id ? 0.5 : 1,
                    transition: 'all var(--dur-fast)',
                  }}
                  onMouseEnter={e => { if (kickingId !== m.user_id) e.currentTarget.style.background = 'rgba(220,38,38,0.06)'; }}
                  onMouseLeave={e => (e.currentTarget.style.background = 'none')}
                >
                  {kickingId === m.user_id ? '...' : 'Kick'}
                </button>
              )}
            </div>
          );
        })}
      </div>

      {/* Leave room */}
      <div style={{ borderTop: '1px solid var(--border-light)', paddingTop: '20px' }}>
        {!confirmLeave ? (
          <button
            onClick={() => setConfirmLeave(true)}
            style={{
              background: 'none',
              border: '1px solid rgba(220,38,38,0.35)',
              borderRadius: 'var(--radius-md)',
              padding: '9px 18px',
              fontSize: '13px',
              color: '#dc2626',
              cursor: 'pointer',
              transition: 'all var(--dur-fast)',
            }}
            onMouseEnter={e => {
              e.currentTarget.style.background = 'rgba(220,38,38,0.06)';
              e.currentTarget.style.borderColor = 'rgba(220,38,38,0.6)';
            }}
            onMouseLeave={e => {
              e.currentTarget.style.background = 'none';
              e.currentTarget.style.borderColor = 'rgba(220,38,38,0.35)';
            }}
          >
            Leave Room
          </button>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <p style={{ fontSize: '13px', color: 'var(--text-secondary)', margin: 0 }}>
              Are you sure you want to leave <strong>{roomName}</strong>?
              {isLeader && (
                <span style={{ display: 'block', fontSize: '12px', color: 'var(--text-dim)', marginTop: '4px' }}>
                  You are the room leader — the room will remain but without a leader.
                </span>
              )}
            </p>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                onClick={() => setConfirmLeave(false)}
                className="btn-ghost"
                style={{ flex: 1, fontSize: '13px', padding: '8px' }}
              >
                Cancel
              </button>
              <button
                onClick={handleLeave}
                disabled={leavingLoading}
                style={{
                  flex: 2,
                  background: '#dc2626',
                  border: 'none',
                  borderRadius: 'var(--radius-md)',
                  padding: '8px',
                  fontSize: '13px',
                  color: '#fff',
                  cursor: leavingLoading ? 'default' : 'pointer',
                  opacity: leavingLoading ? 0.7 : 1,
                  transition: 'opacity var(--dur-fast)',
                }}
              >
                {leavingLoading ? 'Leaving...' : 'Leave Room'}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
