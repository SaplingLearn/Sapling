'use client';

import { useEffect, useState, Suspense } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import RoomList from '@/components/RoomList';
import RoomOverview from '@/components/RoomOverview';
import StudyMatch from '@/components/StudyMatch';
import SchoolDirectory from '@/components/SchoolDirectory';
import RoomChat from '@/components/RoomChat';
import RoomMembers from '@/components/RoomMembers';
import { Room, RoomActivity, RoomMember, RoomOverviewData, StudyMatch as StudyMatchType } from '@/lib/types';
import { getUserRooms, getRoomOverview, getRoomActivity, findStudyMatches } from '@/lib/api';
import { useUser } from '@/context/UserContext';

function useIsMobile(breakpoint = 768) {
  const [isMobile, setIsMobile] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia(`(max-width: ${breakpoint}px)`);
    setIsMobile(mql.matches);
    const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches);
    mql.addEventListener('change', handler);
    return () => mql.removeEventListener('change', handler);
  }, [breakpoint]);
  return isMobile;
}

type Tab = 'overview' | 'chat' | 'match' | 'activity';

function SocialPageInner() {
  const { userId: USER_ID, userReady } = useUser();
  const searchParams = useSearchParams();
  const router = useRouter();
  const suggestConcept = searchParams.get('suggest') ?? '';

  const isMobile = useIsMobile();
  const [showRooms, setShowRooms] = useState(false);
  const [rooms, setRooms] = useState<Room[]>([]);
  const [activeRoomId, setActiveRoomId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>('overview');
  const [schoolView, setSchoolView] = useState(false);
  const [showMembers, setShowMembers] = useState(false);

  const [overviewData, setOverviewData] = useState<RoomOverviewData | null>(null);
  const [activity, setActivity] = useState<RoomActivity[]>([]);
  const [matches, setMatches] = useState<StudyMatchType[]>([]);
  const [matchLoading, setMatchLoading] = useState(false);
  const [overviewLoading, setOverviewLoading] = useState(false);

  // Auto-switch to overview tab when a suggestion is present
  useEffect(() => {
    if (suggestConcept) { setTab('overview'); setShowMembers(false); }
  }, [suggestConcept]);

  // Reset members panel when switching rooms
  useEffect(() => {
    setShowMembers(false);
  }, [activeRoomId]);

  useEffect(() => {
    if (!userReady) return;
    getUserRooms(USER_ID).then(res => {
      setRooms(res.rooms);
      if (res.rooms.length > 0 && !activeRoomId) {
        setActiveRoomId(res.rooms[0].id);
      }
    }).catch(console.error);
    // Intentionally omit activeRoomId: only seed initial selection when rooms load, not on every room switch
    // eslint-disable-next-line react-hooks/exhaustive-deps -- see above
  }, [USER_ID, userReady]);

  useEffect(() => {
    if (!activeRoomId) return;
    setOverviewLoading(true);
    setOverviewData(null);
    setActivity([]);
    setMatches([]);

    Promise.all([
      getRoomOverview(activeRoomId),
      getRoomActivity(activeRoomId),
    ]).then(([ovData, actData]) => {
      setOverviewData(ovData);
      setActivity(actData.activities);
    }).catch(console.error).finally(() => {
      setOverviewLoading(false);
    });
  }, [activeRoomId]);

  const handleFindMatches = async () => {
    if (!activeRoomId) return;
    setMatchLoading(true);
    try {
      const res = await findStudyMatches(activeRoomId, USER_ID);
      setMatches(res.matches);
    } catch (e) {
      console.error(e);
    } finally {
      setMatchLoading(false);
    }
  };

  const handleLeaveRoom = () => {
    setRooms(prev => prev.filter(r => r.id !== activeRoomId));
    const remaining = rooms.filter(r => r.id !== activeRoomId);
    setActiveRoomId(remaining.length > 0 ? remaining[0].id : null);
    setShowMembers(false);
  };

  const handleMembersChange = (updatedMembers: { user_id: string; name: string }[]) => {
    setOverviewData(prev =>
      prev
        ? {
            ...prev,
            members: prev.members.filter(m => updatedMembers.some(u => u.user_id === m.user_id)),
          }
        : prev
    );
  };

  const formatActivityTime = (iso: string) => {
    const diff = Date.now() - new Date(iso).getTime();
    const hrs = Math.floor(diff / 3600000);
    if (hrs < 1) return 'just now';
    if (hrs < 24) return `${hrs}h ago`;
    return `${Math.floor(hrs / 24)}d ago`;
  };

  const tabStyle = (t: Tab) => ({
    background: 'none',
    border: 'none',
    fontSize: '14px',
    fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
    color: !showMembers && tab === t ? '#111827' : '#6b7280',
    fontWeight: !showMembers && tab === t ? 500 : 400 as const,
    borderBottom: !showMembers && tab === t ? '2px solid rgba(26,92,42,0.7)' : '2px solid transparent',
    cursor: 'pointer',
    padding: '8px 0',
    marginRight: '20px',
  });

  // Find the suggested node ID from the current user's graph in overviewData
  const myMemberData = overviewData?.members?.find((m: RoomMember) => m.user_id === USER_ID);
  const suggestNodeId: string | undefined =
    suggestConcept && myMemberData
      ? myMemberData.graph.nodes.find(n => n.concept_name === suggestConcept)?.id
      : undefined;

  const memberCount = overviewData?.members?.length ?? null;

  return (
    <div style={{ display: 'flex', flexDirection: isMobile ? 'column' as const : 'row' as const, height: isMobile ? 'auto' : 'calc(100vh - 48px)', minHeight: isMobile ? 'calc(100vh - 48px)' : undefined }}>
      {/* Left sidebar */}
      {(!isMobile || showRooms) && (
      <div className="panel-in panel-in-1" style={{ width: isMobile ? '100%' : '240px', maxHeight: isMobile ? '300px' : undefined, background: 'rgba(255, 255, 255, 0.32)', backdropFilter: 'blur(16px) saturate(1.5)', WebkitBackdropFilter: 'blur(16px) saturate(1.5)', borderRight: '1px solid rgba(255, 255, 255, 0.55)', overflowY: 'auto' }}>
        <RoomList
          rooms={rooms}
          activeRoomId={schoolView ? null : activeRoomId}
          userId={USER_ID}
          onSelectRoom={id => { setSchoolView(false); setActiveRoomId(id); setTab('overview'); }}
          onRoomsChange={setRooms}
          schoolActive={schoolView}
          onSchoolClick={() => setSchoolView(true)}
        />
      </div>
      )}

      {isMobile && (
        <button
          onClick={() => setShowRooms(v => !v)}
          style={{
            padding: '8px 16px', fontSize: '13px', fontWeight: 500,
            color: '#1a5c2a', background: 'rgba(26,92,42,0.06)',
            border: 'none', borderBottom: '1px solid rgba(107,114,128,0.12)',
            cursor: 'pointer', width: '100%', textAlign: 'left',
            fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
          }}
        >
          {showRooms ? '▼ Hide Rooms' : '▶ Show Rooms'}
        </button>
      )}

      {/* Main area */}
      <div className="panel-in panel-in-2" style={{ flex: 1, minHeight: isMobile ? 0 : undefined, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
        {schoolView ? (
          <SchoolDirectory currentUserId={USER_ID} />
        ) : activeRoomId ? (
          <>
            {/* Tabs */}
            <div style={{ background: 'rgba(255, 255, 255, 0.32)', backdropFilter: 'blur(16px) saturate(1.5)', WebkitBackdropFilter: 'blur(16px) saturate(1.5)', borderBottom: '1px solid rgba(255, 255, 255, 0.55)', padding: isMobile ? '0 12px' : '0 24px', display: 'flex', alignItems: 'center' }}>
              <button style={tabStyle('overview')} onClick={() => { setTab('overview'); setShowMembers(false); }}>Overview</button>
              <button style={tabStyle('chat')} onClick={() => { setTab('chat'); setShowMembers(false); }}>Chat</button>
              <button style={tabStyle('match')} onClick={() => { setTab('match'); setShowMembers(false); }}>Study Match</button>
              <button style={tabStyle('activity')} onClick={() => { setTab('activity'); setShowMembers(false); }}>Activity</button>

              {/* Members button — far right */}
              <button
                onClick={() => setShowMembers(s => !s)}
                style={{
                  marginLeft: 'auto',
                  background: showMembers ? 'var(--accent-dim)' : 'none',
                  border: `1px solid ${showMembers ? 'var(--accent-border)' : 'rgba(107,114,128,0.2)'}`,
                  borderRadius: '6px',
                  padding: '4px 10px',
                  fontSize: '13px',
                  color: showMembers ? 'var(--accent)' : '#6b7280',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '5px',
                  transition: 'all var(--dur-fast)',
                  fontFamily: "var(--font-dm-sans), 'DM Sans', sans-serif",
                }}
              >
                <span style={{ fontSize: '14px' }}>👥</span>
                {memberCount !== null && <span>{memberCount}</span>}
              </button>
            </div>

            {/* Tab content */}
            <div style={{
              flex: 1,
              overflowY: showMembers || tab !== 'chat' ? 'auto' : 'hidden',
              padding: !showMembers && tab === 'chat' ? '0' : isMobile ? '12px' : '24px',
            }}>
              {showMembers ? (
                <RoomMembers
                  roomId={activeRoomId}
                  roomName={overviewData?.room?.name ?? ''}
                  leaderId={overviewData?.room?.created_by ?? ''}
                  members={overviewData?.members?.map(m => ({ user_id: m.user_id, name: m.name })) ?? []}
                  currentUserId={USER_ID}
                  onLeave={handleLeaveRoom}
                  onMembersChange={handleMembersChange}
                />
              ) : (
                <>
                  {tab === 'overview' && (
                    overviewLoading ? (
                      <p style={{ color: '#9ca3af', fontSize: '14px' }}>Loading...</p>
                    ) : overviewData ? (
                      <RoomOverview
                        room={overviewData.room}
                        members={overviewData.members}
                        aiSummary={overviewData.ai_summary}
                        myUserId={USER_ID}
                        suggestNodeId={suggestNodeId}
                        suggestConcept={suggestConcept}
                        onSuggestDismiss={() => router.replace('/social')}
                        onSuggestAccept={() => router.push(`/learn?topic=${encodeURIComponent(suggestConcept)}&mode=quiz`)}
                      />
                    ) : null
                  )}

                  {tab === 'chat' && (
                    <RoomChat
                      roomId={activeRoomId}
                      userId={USER_ID}
                      members={overviewData?.members?.map(m => ({ user_id: m.user_id, name: m.name })) ?? []}
                    />
                  )}

                  {tab === 'match' && (
                    <StudyMatch
                      matches={matches}
                      onFindMatches={handleFindMatches}
                      loading={matchLoading}
                      userId={USER_ID}
                    />
                  )}

                  {tab === 'activity' && (
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      {activity.length === 0 ? (
                        <p style={{ color: '#9ca3af', fontSize: '14px' }}>No activity yet.</p>
                      ) : (
                        activity.map(a => (
                          <div key={a.id} style={{ display: 'flex', gap: '8px', alignItems: 'baseline', padding: '6px 0', borderBottom: '1px solid rgba(148,163,184,0.06)' }}>
                            <span style={{ fontSize: '14px', fontWeight: 500, color: '#111827', minWidth: '60px' }}>{a.user_name}</span>
                            <span style={{ fontSize: '13px', color: '#4b5563' }}>
                              {a.activity_type}
                              {a.concept_name && ` ${a.concept_name}`}
                              {a.detail && ` — ${a.detail}`}
                            </span>
                            <span style={{ fontSize: '11px', color: '#9ca3af', marginLeft: 'auto', flexShrink: 0 }}>
                              {formatActivityTime(a.created_at)}
                            </span>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </>
              )}
            </div>
          </>
        ) : (
          <div style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#9ca3af', fontSize: '14px' }}>
            Create or join a room to get started.
          </div>
        )}
      </div>
    </div>
  );
}

export default function SocialPage() {
  return (
    <Suspense fallback={null}>
      <SocialPageInner />
    </Suspense>
  );
}
