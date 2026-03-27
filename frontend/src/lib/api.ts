import type { RoomMessageRow, RoomOverviewData } from '@/lib/types';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? '';

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    headers: { 'Content-Type': 'application/json', ...options?.headers },
    ...options,
  });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  return res.json();
}

// ── Users ─────────────────────────────────────────────────────────────────────

export const getUsers = () =>
  fetchJSON<{ users: { id: string; name: string; room_id: string | null }[] }>('/api/users');

// ── Graph ─────────────────────────────────────────────────────────────────────

export const getGraph = (userId: string) =>
  fetchJSON<{ nodes: any[]; edges: any[]; stats: any }>(`/api/graph/${userId}`);

export const getRecommendations = (userId: string) =>
  fetchJSON<{ recommendations: any[] }>(`/api/graph/${userId}/recommendations`);

export const getCourses = (userId: string) =>
  fetchJSON<{ courses: { id: string; course_name: string; color: string | null; node_count: number; created_at: string }[] }>(
    `/api/graph/${userId}/courses`
  );

export const addCourse = (userId: string, courseName: string, color?: string) =>
  fetchJSON<{ course_name: string; already_existed: boolean }>(`/api/graph/${userId}/courses`, {
    method: 'POST',
    body: JSON.stringify({ course_name: courseName, ...(color ? { color } : {}) }),
  });

export const updateCourseColor = (userId: string, courseName: string, color: string) =>
  fetchJSON<{ updated: boolean }>(
    `/api/graph/${userId}/courses/${encodeURIComponent(courseName)}/color`,
    { method: 'PATCH', body: JSON.stringify({ color }) }
  );

export const deleteCourse = (userId: string, courseName: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/graph/${userId}/courses/${encodeURIComponent(courseName)}`,
    { method: 'DELETE' }
  );

// ── Learn ─────────────────────────────────────────────────────────────────────

export const startSession = (userId: string, topic: string, mode: string, useSharedContext = true) =>
  fetchJSON<{ session_id: string; initial_message: string; graph_state: any }>('/api/learn/start-session', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, topic, mode, use_shared_context: useSharedContext }),
  });

export const sendChat = (sessionId: string, userId: string, message: string, mode: string, useSharedContext = true) =>
  fetchJSON<{ reply: string; graph_update: any; mastery_changes: any[] }>('/api/learn/chat', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId, message, mode, use_shared_context: useSharedContext }),
  });

export const sendAction = (sessionId: string, userId: string, actionType: string, mode: string, useSharedContext = true) =>
  fetchJSON<{ reply: string; graph_update: any }>('/api/learn/action', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId, action_type: actionType, mode, use_shared_context: useSharedContext }),
  });

export const endSession = (sessionId: string, userId: string) =>
  fetchJSON<{ summary: any }>('/api/learn/end-session', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId }),
  });

export const getSessions = (userId: string, limit = 10) =>
  fetchJSON<{
    sessions: {
      id: string;
      topic: string;
      mode: string;
      started_at: string;
      ended_at: string | null;
      message_count: number;
      is_active: boolean;
    }[];
  }>(`/api/learn/sessions/${userId}?limit=${limit}`);

export const switchMode = (sessionId: string, userId: string, newMode: string) =>
  fetchJSON<{ reply: string }>('/api/learn/mode-switch', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId, new_mode: newMode }),
  });

export const deleteSession = (sessionId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/learn/sessions/${sessionId}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' }
  );

export const resumeSession = (sessionId: string) =>
  fetchJSON<{
    session: { id: string; topic: string; mode: string; started_at: string; ended_at: string | null };
    messages: { id: string; role: string; content: string; created_at: string }[];
  }>(`/api/learn/sessions/${sessionId}/resume`);

// ── Quiz ──────────────────────────────────────────────────────────────────────

export const generateQuiz = (userId: string, conceptNodeId: string, numQuestions: number, difficulty: string, useSharedContext = true) =>
  fetchJSON<{ quiz_id: string; questions: any[] }>('/api/quiz/generate', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, concept_node_id: conceptNodeId, num_questions: numQuestions, difficulty, use_shared_context: useSharedContext }),
  });

export const submitQuiz = (quizId: string, answers: any[]) =>
  fetchJSON<{ score: number; total: number; mastery_before: number; mastery_after: number; results: any[] }>('/api/quiz/submit', {
    method: 'POST',
    body: JSON.stringify({ quiz_id: quizId, answers }),
  });

// ── Calendar ──────────────────────────────────────────────────────────────────

export const extractSyllabus = (formData: FormData, userId?: string): Promise<any> => {
  if (userId) formData.set('user_id', userId);
  return fetch(`${API_URL}/api/calendar/extract`, {
    method: 'POST',
    body: formData,
  }).then(async r => {
    let data: Record<string, unknown> = {};
    try {
      data = (await r.json()) as Record<string, unknown>;
    } catch {
      throw new Error(`Could not read server response (HTTP ${r.status}).`);
    }
    if (!r.ok) {
      const detail = data.detail;
      let msg = '';
      if (typeof detail === 'string') msg = detail;
      else if (Array.isArray(detail)) {
        msg = detail
          .map((d: unknown) => (typeof d === 'object' && d && 'msg' in d ? String((d as { msg: string }).msg) : ''))
          .filter(Boolean)
          .join('; ');
      }
      if (!msg && typeof data.error === 'string') msg = data.error;
      throw new Error(msg || `Request failed (HTTP ${r.status}).`);
    }
    return data;
  });
};

export const getUpcomingAssignments = (userId: string) =>
  fetchJSON<{ assignments: any[] }>(`/api/calendar/upcoming/${userId}`);

export const saveAssignments = (userId: string, assignments: any[]) =>
  fetchJSON<{ saved_count: number }>('/api/calendar/save', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, assignments }),
  });

export const getCalendarAuthUrl = (userId: string) =>
  fetchJSON<{ url: string }>(`/api/calendar/auth-url?user_id=${encodeURIComponent(userId)}`);

export const getCalendarStatus = (userId: string) =>
  fetchJSON<{ connected: boolean; expires_at?: string }>(`/api/calendar/status/${userId}`);
export const checkCalendarStatus = getCalendarStatus;

export const syncToGoogleCalendar = (userId: string) =>
  fetchJSON<{ synced_count: number }>('/api/calendar/sync', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const exportToGoogleCalendar = (userId: string, assignmentIds: string[]) =>
  fetchJSON<{ exported_count: number; skipped_count: number }>('/api/calendar/export', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, assignment_ids: assignmentIds }),
  });

export const importGoogleEvents = (userId: string, daysAhead = 30) =>
  fetchJSON<{ events: any[]; count: number }>(
    `/api/calendar/import/${userId}?days_ahead=${daysAhead}`
  );

export const disconnectGoogleCalendar = (userId: string) =>
  fetchJSON<{ disconnected: boolean }>(`/api/calendar/disconnect/${userId}`, {
    method: 'DELETE',
  });

// ── Social ────────────────────────────────────────────────────────────────────

export const createRoom = (userId: string, roomName: string) =>
  fetchJSON<{ room_id: string; invite_code: string }>('/api/social/rooms/create', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, room_name: roomName }),
  });

export const joinRoom = (userId: string, inviteCode: string) =>
  fetchJSON<{ room: any }>('/api/social/rooms/join', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, invite_code: inviteCode }),
  });

export const getUserRooms = (userId: string) =>
  fetchJSON<{ rooms: any[] }>(`/api/social/rooms/${userId}`);

export const getRoomOverview = (roomId: string) =>
  fetchJSON<RoomOverviewData>(`/api/social/rooms/${roomId}/overview`);

export const getRoomActivity = (roomId: string) =>
  fetchJSON<{ activities: any[] }>(`/api/social/rooms/${roomId}/activity`);

export const findStudyMatches = (roomId: string, userId: string) =>
  fetchJSON<{ matches: any[] }>(`/api/social/rooms/${roomId}/match`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const findSchoolMatches = (userId: string) =>
  fetchJSON<{ matches: any[] }>('/api/social/school-match', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const getSchoolStudents = () =>
  fetchJSON<{ students: any[] }>('/api/social/students');

export const leaveRoom = (roomId: string, userId: string) =>
  fetchJSON<{ left: boolean }>(`/api/social/rooms/${roomId}/leave`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const kickMember = (roomId: string, memberId: string, requesterId: string) =>
  fetchJSON<{ kicked: boolean }>(`/api/social/rooms/${roomId}/members/${encodeURIComponent(memberId)}?requester_id=${encodeURIComponent(requesterId)}`, {
    method: 'DELETE',
  });

export const getRoomMessages = (roomId: string) =>
  fetchJSON<{ messages: RoomMessageRow[] }>(`/api/social/rooms/${roomId}/messages`);

export const sendRoomMessage = (roomId: string, userId: string, userName: string, text: string, imageUrl?: string, replyToId?: string) =>
  fetchJSON<{ message: any }>(`/api/social/rooms/${roomId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, user_name: userName, text: text || null, image_url: imageUrl || null, reply_to_id: replyToId || null }),
  });

export const deleteRoomMessage = (roomId: string, messageId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/social/rooms/${roomId}/messages/${encodeURIComponent(messageId)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });

export const editRoomMessage = (roomId: string, messageId: string, userId: string, text: string) =>
  fetchJSON<{ edited: boolean }>(`/api/social/rooms/${roomId}/messages/${encodeURIComponent(messageId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, text }),
  });

export const toggleRoomReaction = (roomId: string, messageId: string, userId: string, emoji: string) =>
  fetchJSON<{ added: boolean }>(`/api/social/rooms/${roomId}/messages/${encodeURIComponent(messageId)}/reactions`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, emoji }),
  });

// ── Documents ─────────────────────────────────────────────────────────────────

export const getDocuments = (userId: string) =>
  fetchJSON<{ documents: any[] }>(`/api/documents/user/${userId}`);

export const deleteDocument = (documentId: string, userId?: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/documents/doc/${documentId}${userId ? `?user_id=${encodeURIComponent(userId)}` : ''}`, { method: 'DELETE' });

export const updateDocument = (documentId: string, data: { category?: string; user_id?: string }) =>
  fetchJSON<any>(`/api/documents/doc/${documentId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });

export const uploadDocument = (formData: FormData, init?: RequestInit): Promise<any> =>
  fetch(`${API_URL}/api/documents/upload`, { method: 'POST', body: formData, ...init }).then(async r => {
    if (!r.ok) { const e = await r.text(); throw new Error(e || `HTTP ${r.status}`); }
    return r.json();
  });

// ── Flashcards ────────────────────────────────────────────────────────────────

export const generateFlashcards = (userId: string, topic: string, count = 5, sessionId?: string) =>
  fetchJSON<{ flashcards: any[]; context_used?: { documents_found: number; weak_concepts_found: number } }>('/api/flashcards/generate', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, topic, count, ...(sessionId ? { session_id: sessionId } : {}) }),
  });

export const getFlashcards = (userId: string, topic?: string) =>
  fetchJSON<{ flashcards: any[] }>(
    `/api/flashcards/user/${userId}${topic ? `?topic=${encodeURIComponent(topic)}` : ''}`
  );

export const rateFlashcard = (userId: string, cardId: string, rating: number) =>
  fetchJSON<{ ok: boolean }>('/api/flashcards/rate', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, card_id: cardId, rating }),
  });

export const deleteFlashcard = (userId: string, cardId: string) =>
  fetchJSON<{ ok: boolean }>(`/api/flashcards/${cardId}?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });

// ── Feedback ──────────────────────────────────────────────────────────────────

export const submitFeedback = (data: {
  user_id: string; type: 'global' | 'session'; rating: number;
  selected_options: string[]; comment?: string; session_id?: string; topic?: string;
}) => fetchJSON<{ ok: boolean }>('/api/feedback', { method: 'POST', body: JSON.stringify(data) });

export const submitIssueReport = (data: {
  user_id: string; topic: string; description: string; screenshot_urls: string[];
}) => fetchJSON<{ ok: boolean }>('/api/issue-reports', { method: 'POST', body: JSON.stringify(data) });

// ── Careers ───────────────────────────────────────────────────────────────────

export const submitJobApplication = async (data: {
  position: string;
  full_name: string;
  email: string;
  phone: string;
  linkedin_url: string;
  resume?: File | null;
}): Promise<{ ok: boolean; id: string | null }> => {
  const formData = new FormData();
  formData.append('position', data.position);
  formData.append('full_name', data.full_name);
  formData.append('email', data.email);
  formData.append('phone', data.phone);
  formData.append('linkedin_url', data.linkedin_url);
  if (data.resume) formData.append('resume', data.resume);

  const res = await fetch(`${API_URL}/api/careers/apply`, { method: 'POST', body: formData });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  return res.json();
};