import type {
  RoomMessageRow, RoomOverviewData,
  UserProfile, UserSettings, UserRole, UserAchievement, Achievement,
  UserCosmetic, CosmeticType, Role, Cosmetic, RarityTier, AchievementCategory,
} from '@/lib/types';

import { handleLocalRequest } from '@/lib/localData';

const API_URL = process.env.NEXT_PUBLIC_API_URL ?? '';
export const IS_LOCAL_MODE = process.env.NEXT_PUBLIC_LOCAL_MODE === 'true';

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  if (IS_LOCAL_MODE) {
    return handleLocalRequest(path, options) as T;
  }
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

// Users
export const getUsers = () =>
  fetchJSON<{ users: { id: string; name: string; room_id: string | null }[] }>('/api/users');

// Graph
export const getGraph = (userId: string) =>
  fetchJSON<{ nodes: any[]; edges: any[]; stats: any }>(`/api/graph/${userId}`);

export const getRecommendations = (userId: string) =>
  fetchJSON<{ recommendations: any[] }>(`/api/graph/${userId}/recommendations`);

export interface EnrolledCourse {
  enrollment_id: string;
  course_id: string;
  course_code: string;
  course_name: string;
  school: string;
  department: string;
  color: string | null;
  nickname: string | null;
  node_count: number;
  enrolled_at: string;
}

export const getCourses = (userId: string) =>
  fetchJSON<{ courses: EnrolledCourse[] }>(`/api/graph/${userId}/courses`);

export const addCourse = (userId: string, courseId: string, color?: string, nickname?: string) =>
  fetchJSON<{ course_id: string; already_existed: boolean; error?: string }>(`/api/graph/${userId}/courses`, {
    method: 'POST',
    body: JSON.stringify({ course_id: courseId, ...(color ? { color } : {}), ...(nickname ? { nickname } : {}) }),
  });

export const deleteCourse = (userId: string, courseId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/graph/${userId}/courses/${encodeURIComponent(courseId)}`,
    { method: 'DELETE' }
  );

export const updateCourseColor = (userId: string, courseId: string, color: string) =>
  fetchJSON<{ updated: boolean }>(
    `/api/graph/${userId}/courses/${encodeURIComponent(courseId)}/color`,
    { method: 'PATCH', body: JSON.stringify({ color }) }
  );

// Learn
export const startSession = (userId: string, topic: string, mode: string, courseId?: string, useSharedContext = true) =>
  fetchJSON<{ session_id: string; initial_message: string; graph_state: any }>('/api/learn/start-session', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, topic, mode, use_shared_context: useSharedContext, course_id: courseId }),
  });

export const sendChat = (sessionId: string, userId: string, message: string, mode: string, useSharedContext = true) =>
  fetchJSON<{ reply: string; graph_update: any; mastery_changes: any[] }>('/api/learn/chat', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId, message, mode, use_shared_context: useSharedContext }),
  });

export interface SessionSummaryData {
  concepts_covered: string[];
  mastery_changes: { concept: string; before: number; after: number }[];
  new_connections: { source: string; target: string }[];
  time_spent_minutes: number;
  recommended_next: string[];
}

export const endSession = (sessionId: string, userId: string) =>
  fetchJSON<{ summary: SessionSummaryData }>('/api/learn/end-session', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId }),
  });

export const learnAction = (
  sessionId: string,
  userId: string,
  actionType: 'hint' | 'confused' | 'skip',
  mode: string,
  useSharedContext = true,
) =>
  fetchJSON<{ reply: string; graph_update: any }>('/api/learn/action', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      user_id: userId,
      action_type: actionType,
      mode,
      use_shared_context: useSharedContext,
    }),
  });

export interface Session {
  id: string;
  topic: string;
  mode: string;
  course_id: string | null;
  started_at: string;
  ended_at: string | null;
  message_count: number;
  is_active: boolean;
}

export const getSessions = (userId: string, limit = 10) =>
  fetchJSON<{ sessions: Session[] }>(`/api/learn/sessions/${userId}?limit=${limit}`);

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
    session: { id: string; user_id: string; topic: string; mode: string; course_id: string | null; started_at: string; ended_at: string | null };
    messages: { id: string; role: string; content: string; created_at: string }[];
  }>(`/api/learn/sessions/${sessionId}/resume`);

// Quiz
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

// Calendar
export interface Assignment {
  id: string;
  user_id: string;
  title: string;
  due_date: string;
  assignment_type?: string;
  notes?: string;
  google_event_id?: string;
  course_id?: string;
  course_code?: string;
  course_name?: string;
}

export const getUpcomingAssignments = (userId: string) =>
  fetchJSON<{ assignments: Assignment[] }>(`/api/calendar/upcoming/${userId}`);

export const getAllAssignments = (userId: string) =>
  fetchJSON<{ assignments: Assignment[] }>(`/api/calendar/all/${userId}`);

export const extractSyllabus = (formData: FormData, userId?: string): Promise<any> => {
  if (IS_LOCAL_MODE) return Promise.resolve({ assignments: [] });
  if (userId) formData.set('user_id', userId);
  return fetch(`${API_URL}/api/calendar/extract`, { method: 'POST', body: formData })
    .then(async r => { const data = await r.json(); if (!r.ok) throw new Error(String(data?.detail || `HTTP ${r.status}`)); return data; });
};

export const saveAssignments = (userId: string, assignments: Array<{ title: string; course_id?: string; due_date: string; assignment_type?: string | null; notes?: string | null }>) =>
  fetchJSON<{ saved_count: number }>('/api/calendar/save', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, assignments }),
  });

export const updateAssignment = (
  assignmentId: string,
  userId: string,
  patch: Partial<Pick<Assignment, 'title' | 'course_id' | 'due_date' | 'assignment_type' | 'notes'>>,
) =>
  fetchJSON<{ updated: boolean }>(`/api/calendar/assignments/${encodeURIComponent(assignmentId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, ...patch }),
  });

export const deleteAssignment = (assignmentId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/calendar/assignments/${encodeURIComponent(assignmentId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const getCalendarStatus = (userId: string) =>
  fetchJSON<{ connected: boolean; expires_at?: string }>(`/api/calendar/status/${userId}`);

export const disconnectCalendar = (userId: string) =>
  fetchJSON<{ disconnected: boolean }>(`/api/calendar/disconnect/${userId}`, { method: 'DELETE' });

export const syncCalendar = (userId: string) =>
  fetchJSON<{ synced_count: number }>('/api/calendar/sync', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export interface GoogleEvent {
  google_event_id: string;
  title: string;
  description?: string;
  start_date: string;
  end_date: string;
  start_datetime?: string | null;
  end_datetime?: string | null;
  all_day: boolean;
  html_link?: string;
  location?: string;
}

export const importGoogleEvents = (userId: string, daysAhead = 60) =>
  fetchJSON<{ events: GoogleEvent[]; count: number }>(
    `/api/calendar/import/${encodeURIComponent(userId)}?days_ahead=${daysAhead}`,
  );

export const calendarAuthUrl = (userId: string) =>
  `${API_URL}/api/calendar/auth-url?user_id=${encodeURIComponent(userId)}`;

export const exportToGoogleCalendar = (userId: string, assignmentIds: string[]) =>
  fetchJSON<{ exported_count: number; skipped_count: number }>('/api/calendar/export', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, assignment_ids: assignmentIds }),
  });

// Social
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

export const getRoomMessages = (roomId: string, opts?: { before?: string; limit?: number }) => {
  const params = new URLSearchParams();
  if (opts?.before) params.set('before', opts.before);
  if (opts?.limit) params.set('limit', String(opts.limit));
  const qs = params.toString();
  return fetchJSON<{ messages: RoomMessageRow[]; has_more?: boolean }>(
    `/api/social/rooms/${roomId}/messages${qs ? `?${qs}` : ''}`,
  );
};

export const sendRoomMessage = (roomId: string, userId: string, userName: string, text: string, imageUrl?: string, replyToId?: string) =>
  fetchJSON<{ message: any }>(`/api/social/rooms/${roomId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, user_name: userName, text: text || null, image_url: imageUrl || null, reply_to_id: replyToId || null }),
  });

export const toggleRoomReaction = (roomId: string, messageId: string, userId: string, emoji: string) =>
  fetchJSON<{ added: boolean }>(`/api/social/rooms/${roomId}/messages/${encodeURIComponent(messageId)}/reactions`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, emoji }),
  });

export const editRoomMessage = (roomId: string, messageId: string, userId: string, text: string) =>
  fetchJSON<{ edited: boolean }>(`/api/social/rooms/${roomId}/messages/${encodeURIComponent(messageId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, text }),
  });

export const deleteRoomMessage = (roomId: string, messageId: string, userId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/social/rooms/${roomId}/messages/${encodeURIComponent(messageId)}?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
  });

export const leaveRoom = (roomId: string, userId: string) =>
  fetchJSON<{ left: boolean }>(`/api/social/rooms/${roomId}/leave`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const kickMember = (roomId: string, memberId: string, requesterId: string) =>
  fetchJSON<{ kicked: boolean }>(
    `/api/social/rooms/${roomId}/members/${encodeURIComponent(memberId)}?requester_id=${encodeURIComponent(requesterId)}`,
    { method: 'DELETE' },
  );

export interface StudentRow {
  user_id: string;
  name: string;
  streak: number;
  courses: string[];
  stats: { mastered: number; learning: number; struggling: number; unexplored: number; total: number };
  top_concepts: string[];
}

export const getStudents = () =>
  fetchJSON<{ students: StudentRow[] }>(`/api/social/students`);

export const schoolMatch = (userId: string) =>
  fetchJSON<{ matches: any[] }>('/api/social/school-match', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

// Documents
export const getDocuments = (userId: string) =>
  fetchJSON<{ documents: any[] }>(`/api/documents/user/${userId}`);

export const deleteDocument = (documentId: string, userId?: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/documents/doc/${documentId}${userId ? `?user_id=${encodeURIComponent(userId)}` : ''}`, { method: 'DELETE' });

export const uploadDocument = (formData: FormData, signal?: AbortSignal): Promise<any> => {
  if (IS_LOCAL_MODE) return Promise.resolve({ id: 'local-doc', status: 'processed' });
  return fetch(`${API_URL}/api/documents/upload`, { method: 'POST', body: formData, signal })
    .then(async r => { if (!r.ok) { const e = await r.text(); throw new Error(e || `HTTP ${r.status}`); } return r.json(); });
};

export const updateDocumentCategory = (documentId: string, userId: string, category: string) =>
  fetchJSON<{ id: string; category: string }>(`/api/documents/doc/${documentId}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, category }),
  });

// Flashcards
export interface GenerateFlashcardsResponse {
  flashcards: any[];
  context_used?: { documents_found: number; weak_concepts_found: number };
}

export const generateFlashcards = (userId: string, topic: string, count = 5) =>
  fetchJSON<GenerateFlashcardsResponse>('/api/flashcards/generate', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, topic, count }),
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
  fetchJSON<{ ok: boolean }>(
    `/api/flashcards/${encodeURIComponent(cardId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

// Study Guide
export interface StudyGuideTopic {
  name: string;
  importance: string;
  concepts: string[];
}

export interface StudyGuideContent {
  exam: string;
  due_date: string;
  overview: string;
  topics: StudyGuideTopic[];
}

export interface StudyGuideExam {
  id: string;
  title: string;
  due_date: string;
  assignment_type?: string | null;
}

export interface StudyGuideCacheEntry {
  id: string;
  course_id: string;
  exam_id: string;
  course_name: string;
  exam_title: string;
  overview: string;
  generated_at: string;
}

export const getStudyGuideExams = (userId: string, courseId: string) =>
  fetchJSON<{ exams: StudyGuideExam[] }>(
    `/api/study-guide/${encodeURIComponent(userId)}/exams?course_id=${encodeURIComponent(courseId)}`,
  );

export const getStudyGuide = (userId: string, courseId: string, examId: string) =>
  fetchJSON<{ guide: StudyGuideContent; generated_at: string; cached: boolean }>(
    `/api/study-guide/${encodeURIComponent(userId)}/guide?course_id=${encodeURIComponent(courseId)}&exam_id=${encodeURIComponent(examId)}`,
  );

export const regenerateStudyGuide = (userId: string, courseId: string, examId: string) =>
  fetchJSON<{ success: boolean; guide: StudyGuideContent; generated_at: string }>(
    '/api/study-guide/regenerate',
    {
      method: 'POST',
      body: JSON.stringify({ user_id: userId, course_id: courseId, exam_id: examId }),
    },
  );

export const getCachedStudyGuides = (userId: string) =>
  fetchJSON<{ guides: StudyGuideCacheEntry[] }>(`/api/study-guide/${encodeURIComponent(userId)}/cached`);

// Feedback
export const submitFeedback = (data: {
  user_id: string; type: 'global' | 'session'; rating: number;
  selected_options: string[]; comment?: string; session_id?: string; topic?: string;
}) => fetchJSON<{ ok: boolean }>('/api/feedback', { method: 'POST', body: JSON.stringify(data) });

export const submitIssueReport = (data: {
  user_id: string; topic: string; description: string; screenshot_urls: string[];
}) => fetchJSON<{ ok: boolean }>('/api/issue-reports', { method: 'POST', body: JSON.stringify(data) });

// Onboarding
export interface OnboardingCourse {
  id: string;
  course_code: string;
  course_name: string;
}

export const onboardingCoursesSearch = (q: string) =>
  fetchJSON<{ courses: OnboardingCourse[] }>(
    `/api/onboarding/courses${q ? `?q=${encodeURIComponent(q)}` : ''}`,
  );

export interface OnboardingProfilePayload {
  user_id: string;
  first_name: string;
  last_name: string;
  year: string;
  majors: string[];
  minors: string[];
  course_ids: string[];
  learning_style: 'visual' | 'reading' | 'auditory' | 'hands-on' | 'mixed';
}

export const submitOnboardingProfile = (payload: OnboardingProfilePayload) =>
  fetchJSON<{ user_id: string; courses_linked: string[] }>('/api/onboarding/profile', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

// Profile
export const fetchPublicProfile = (userId: string) =>
  fetchJSON<UserProfile>(`/api/profile/${userId}`);

export const checkUsername = (username: string, userId?: string) =>
  fetchJSON<{ available: boolean; reason?: 'taken' | 'invalid' | 'self' }>(
    `/api/profile/username/check?username=${encodeURIComponent(username)}${userId ? `&user_id=${encodeURIComponent(userId)}` : ''}`,
  );

export const setFeaturedAchievements = (userId: string, achievementIds: string[]) =>
  fetchJSON<{ updated: boolean }>(`/api/profile/${userId}/featured-achievements?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: JSON.stringify({ achievement_ids: achievementIds }),
  });

export const setFeaturedRole = (userId: string, roleId: string | null) =>
  fetchJSON<{ updated: boolean }>(`/api/profile/${userId}/featured-role?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: JSON.stringify({ role_id: roleId }),
  });

export const exportData = (userId: string) =>
  fetchJSON<Record<string, unknown>>(`/api/profile/${userId}/export?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST',
  });

export const updateProfile = (userId: string, data: Partial<UserProfile>) =>
  fetchJSON<{ updated: boolean }>(`/api/profile/${userId}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });

export const fetchSettings = (userId: string) =>
  fetchJSON<UserSettings>(`/api/profile/${userId}/settings?user_id=${encodeURIComponent(userId)}`);

export const updateSettings = (userId: string, data: Partial<UserSettings>) =>
  fetchJSON<UserSettings>(`/api/profile/${userId}/settings?user_id=${encodeURIComponent(userId)}`, {
    method: 'PATCH',
    body: JSON.stringify(data),
  });

export const equipCosmetic = (userId: string, slot: CosmeticType, cosmeticId: string | null) =>
  fetchJSON<{ equipped: boolean }>(`/api/profile/${userId}/equip?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST',
    body: JSON.stringify({ slot, cosmetic_id: cosmeticId }),
  });

export const fetchAchievements = (userId: string) =>
  fetchJSON<{ earned: UserAchievement[]; available: Achievement[] }>(`/api/profile/${userId}/achievements`);

export const fetchCosmetics = (userId: string) =>
  fetchJSON<{ cosmetics: Record<CosmeticType, UserCosmetic[]>; equipped: Record<string, any> }>(
    `/api/profile/${userId}/cosmetics?user_id=${encodeURIComponent(userId)}`
  );

export interface CatalogCosmetic extends Cosmetic {
  unlock_source?: string | null;
  owned: boolean;
}

export const fetchCosmeticsCatalog = (userId: string) =>
  fetchJSON<{ catalog: Record<CosmeticType, CatalogCosmetic[]> }>(
    `/api/profile/${userId}/cosmetics/catalog?user_id=${encodeURIComponent(userId)}`
  );

export const fetchRoles = (userId: string) =>
  fetchJSON<{ roles: UserRole[] }>(`/api/profile/${userId}/roles`);

export const deleteAccount = (userId: string, confirmation: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/profile/${userId}/account?user_id=${encodeURIComponent(userId)}`, {
    method: 'DELETE',
    body: JSON.stringify({ confirmation }),
  });

// Admin
export const adminFetchUsers = () =>
  fetchJSON<{ users: any[] }>('/api/admin/users');

export const adminApproveUser = (userId: string) =>
  fetchJSON<{ approved: boolean }>(`/api/admin/users/${userId}/approve`, { method: 'PATCH' });

export const adminAssignRole = (userId: string, roleId: string, grantedBy?: string) =>
  fetchJSON<{ assigned: boolean }>('/api/admin/roles/assign', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, role_id: roleId, granted_by: grantedBy }),
  });

export const adminRevokeRole = (userId: string, roleId: string) =>
  fetchJSON<{ revoked: boolean }>('/api/admin/roles/revoke', {
    method: 'DELETE',
    body: JSON.stringify({ user_id: userId, role_id: roleId }),
  });

export const adminListRoles = () =>
  fetchJSON<{ roles: Role[] }>('/api/admin/roles');

export const adminCreateRole = (payload: {
  name: string; slug: string; color: string; icon?: string | null;
  description?: string | null; is_staff_assigned?: boolean;
  is_earnable?: boolean; display_priority?: number;
}) =>
  fetchJSON<{ role: Role }>('/api/admin/roles', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminDeleteRole = (roleId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/roles/${encodeURIComponent(roleId)}`, { method: 'DELETE' });

export const adminListAchievements = () =>
  fetchJSON<{ achievements: Achievement[] }>('/api/admin/achievements');

export const adminCreateAchievement = (payload: {
  name: string; slug: string; description?: string | null; icon?: string | null;
  category: AchievementCategory; rarity: RarityTier; is_secret?: boolean;
}) =>
  fetchJSON<{ achievement: Achievement }>('/api/admin/achievements', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminDeleteAchievement = (achievementId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/achievements/${encodeURIComponent(achievementId)}`, { method: 'DELETE' });

export const adminGrantAchievement = (userId: string, achievementId: string) =>
  fetchJSON<{ granted: boolean }>('/api/admin/achievements/grant', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, achievement_id: achievementId }),
  });

export const adminListCosmetics = () =>
  fetchJSON<{ cosmetics: Cosmetic[] }>('/api/admin/cosmetics');

export const adminCreateCosmetic = (payload: {
  type: CosmeticType; name: string; slug: string;
  asset_url?: string | null; css_value?: string | null;
  rarity: RarityTier; unlock_source?: string | null;
}) =>
  fetchJSON<{ cosmetic: Cosmetic }>('/api/admin/cosmetics', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminDeleteCosmetic = (cosmeticId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/cosmetics/${encodeURIComponent(cosmeticId)}`, { method: 'DELETE' });

// Careers
export const submitJobApplication = async (data: {
  position: string;
  full_name: string;
  email: string;
  phone: string;
  linkedin_url: string;
  portfolio_link?: string;
  resume?: File | null;
}): Promise<{ ok: boolean; id: string | null }> => {
  if (IS_LOCAL_MODE) return { ok: true, id: null };
  const formData = new FormData();
  formData.append('position', data.position);
  formData.append('full_name', data.full_name);
  formData.append('email', data.email);
  formData.append('phone', data.phone);
  formData.append('linkedin_url', data.linkedin_url);
  if (data.portfolio_link) formData.append('portfolio_link', data.portfolio_link);
  if (data.resume) formData.append('resume', data.resume);

  const res = await fetch(`${API_URL}/api/careers/apply`, { method: 'POST', body: formData });
  if (!res.ok) {
    const err = await res.text();
    throw new Error(err || `HTTP ${res.status}`);
  }
  return res.json();
};

export const uploadAvatar = (userId: string, file: File): Promise<{ avatar_url: string }> => {
  if (IS_LOCAL_MODE) return Promise.resolve({ avatar_url: URL.createObjectURL(file) });
  const fd = new FormData();
  fd.append('file', file);
  return fetch(`${API_URL}/api/profile/${encodeURIComponent(userId)}/avatar?user_id=${encodeURIComponent(userId)}`, {
    method: 'POST', body: fd,
  }).then(async r => {
    if (!r.ok) throw new Error(await r.text() || `HTTP ${r.status}`);
    return r.json();
  });
};
