import type {
  RoomMessageRow, RoomOverviewData,
  UserProfile, UserSettings, UserRole, UserAchievement, Achievement,
  UserCosmetic, CosmeticType, Role, Cosmetic, RarityTier, AchievementCategory,
  GradebookSummary, GradebookCourse, GradeCategory, GradedAssignment, LetterScaleTier,
  ExtractedSyllabusCategory,
  AllowlistEmail, AchievementTrigger, AdminAuditEntry, AnalyticsOverview, PaginatedUsers,
} from '@/lib/types';

import { handleLocalRequest } from '@/lib/localData';

export const API_URL = process.env.NEXT_PUBLIC_API_URL ?? '';
export const IS_LOCAL_MODE = process.env.NEXT_PUBLIC_LOCAL_MODE === 'true';

async function fetchJSON<T>(path: string, options?: RequestInit): Promise<T> {
  if (IS_LOCAL_MODE) {
    return handleLocalRequest(path, options) as T;
  }
  const res = await fetch(`${API_URL}${path}`, {
    credentials: 'include',
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

export const deleteGraphNode = (userId: string, nodeId: string) =>
  fetchJSON<{ deleted: boolean }>(
    `/api/graph/${userId}/nodes/${encodeURIComponent(nodeId)}`,
    { method: 'DELETE' }
  );

// Learn
export type ModelPref = 'smart' | 'fast';

export const startSession = (
  userId: string,
  topic: string,
  mode: string,
  courseId?: string,
  useSharedContext = true,
  modelPref?: ModelPref,
) =>
  fetchJSON<{ session_id: string; initial_message: string; graph_state: any }>('/api/learn/start-session', {
    method: 'POST',
    body: JSON.stringify({
      user_id: userId,
      topic,
      mode,
      use_shared_context: useSharedContext,
      course_id: courseId,
      ...(modelPref ? { model_pref: modelPref } : {}),
    }),
  });

export const sendChat = (
  sessionId: string,
  userId: string,
  message: string,
  mode: string,
  useSharedContext = true,
  modelPref?: ModelPref,
) =>
  fetchJSON<{ reply: string; graph_update: any; mastery_changes: any[] }>('/api/learn/chat', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      user_id: userId,
      message,
      mode,
      use_shared_context: useSharedContext,
      ...(modelPref ? { model_pref: modelPref } : {}),
    }),
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
  modelPref?: ModelPref,
) =>
  fetchJSON<{ reply: string; graph_update: any }>('/api/learn/action', {
    method: 'POST',
    body: JSON.stringify({
      session_id: sessionId,
      user_id: userId,
      action_type: actionType,
      mode,
      use_shared_context: useSharedContext,
      ...(modelPref ? { model_pref: modelPref } : {}),
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
  return fetch(`${API_URL}/api/calendar/extract`, { method: 'POST', body: formData, credentials: 'include' })
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
  // Non-streaming JSON upload. Hits /upload/sync (legacy contract) so callers
  // that don't care about progress events stay one-line. The streaming /upload
  // route is exposed separately via uploadDocumentStream below.
  if (IS_LOCAL_MODE) return Promise.resolve({ id: 'local-doc', status: 'processed' });
  return fetch(`${API_URL}/api/documents/upload/sync`, { method: 'POST', body: formData, signal, credentials: 'include' })
    .then(async r => { if (!r.ok) { const e = await r.text(); throw new Error(e || `HTTP ${r.status}`); } return r.json(); });
};

// Streaming upload — emits SaplingEvent SSE events while the orchestrator runs.
// Event types match backend/services/agent_events.py::SaplingEvent.
export type UploadEventType = 'status' | 'progress' | 'result' | 'error';

export interface UploadEvent {
  type: UploadEventType;
  step: string;
  message: string;
  data?: Record<string, unknown> | null;
}

export async function uploadDocumentStream(
  formData: FormData,
  onEvent: (event: UploadEvent) => void,
  signal?: AbortSignal,
  requestId?: string,
): Promise<any> {
  if (IS_LOCAL_MODE) {
    onEvent({ type: 'status', step: 'done', message: 'Saved.' });
    return { id: 'local-doc', status: 'processed' };
  }
  const { streamSSE } = await import('./sse');
  let finalDoc: any = null;
  const headers: Record<string, string> = {};
  if (requestId) headers['X-Request-ID'] = requestId;
  for await (const e of streamSSE<UploadEvent>(
    `${API_URL}/api/documents/upload`,
    { method: 'POST', body: formData, signal, credentials: 'include', headers },
  )) {
    onEvent(e.data);
    if (e.event === 'result') {
      // result.data carries the full DocumentProcessingResult (orchestrator)
      // OR the legacy-fallback persisted row. Both expose `id`/`document_id`.
      finalDoc = e.data.data ?? null;
    }
    if (e.event === 'status' && e.data.step === 'done') {
      // The done event carries { document_id } when the row persisted.
      const docIdFromDone = (e.data.data as { document_id?: string } | undefined)?.document_id;
      if (docIdFromDone && finalDoc && typeof finalDoc === 'object' && !('id' in finalDoc)) {
        finalDoc = { ...finalDoc, id: docIdFromDone };
      }
    }
  }
  if (!finalDoc) throw new Error('Upload stream ended without a result event.');
  return finalDoc;
}

export const updateDocumentCategory = (documentId: string, userId: string, category: string) =>
  fetchJSON<{ id: string; category: string }>(`/api/documents/doc/${documentId}`, {
    method: 'PATCH',
    body: JSON.stringify({ user_id: userId, category }),
  });

export interface ScanConceptsResponse {
  concepts: string[];
  added: number;
  existing: number;
}

export const scanDocumentConcepts = (documentId: string, userId: string) =>
  fetchJSON<ScanConceptsResponse>(`/api/documents/doc/${documentId}/scan-concepts`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
  });

export const scanCourseConcepts = (courseId: string, userId: string) =>
  fetchJSON<ScanConceptsResponse>(`/api/documents/course/${courseId}/scan-concepts`, {
    method: 'POST',
    body: JSON.stringify({ user_id: userId }),
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

// Flashcard import
export interface ImportCard { front: string; back: string }
export interface ImportParseResponse { cards: ImportCard[]; errors: { row: number; message: string }[] }
export interface ImportCommitResponse { inserted: number; skipped_duplicates: number }
export interface ImportGenerateResponse { cards: ImportCard[] }

export const importParse = (
  userId: string,
  source: "anki" | "xlsx" | "url" | "ocr",
  payload: string,
  options: Record<string, unknown> = {},
) =>
  fetchJSON<ImportParseResponse>(`/api/flashcards/import/parse`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, source, payload, options }),
  });

export const importCommit = (
  userId: string,
  courseId: string | null,
  topic: string,
  cards: ImportCard[],
  dedup = true,
) =>
  fetchJSON<ImportCommitResponse>(`/api/flashcards/import/commit`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, course_id: courseId, topic, cards, dedup }),
  });

export const importGenerate = (
  userId: string,
  args:
    | { source: "paste"; text: string; count: number; difficulty: "recall" | "application" | "conceptual" }
    | { source: "library_doc"; documentId: string; count: number; difficulty: "recall" | "application" | "conceptual" },
) =>
  fetchJSON<ImportGenerateResponse>(`/api/flashcards/import/generate`, {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      source: args.source,
      text: args.source === "paste" ? args.text : undefined,
      document_id: args.source === "library_doc" ? args.documentId : undefined,
      count: args.count,
      difficulty: args.difficulty,
    }),
  });

export const importCleanup = (userId: string, cards: ImportCard[]) =>
  fetchJSON<{ cards: ImportCard[] }>(`/api/flashcards/import/cleanup`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, cards }),
  });

export const importCloze = (userId: string, paragraph: string) =>
  fetchJSON<{ cards: ImportCard[] }>(`/api/flashcards/import/cloze`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, paragraph }),
  });

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

// Admin — users
export const adminFetchUsers = (params?: { q?: string; page?: number; page_size?: number }) => {
  const qp = new URLSearchParams();
  if (params?.q) qp.set('q', params.q);
  if (params?.page) qp.set('page', String(params.page));
  if (params?.page_size) qp.set('page_size', String(params.page_size));
  const suffix = qp.toString() ? `?${qp.toString()}` : '';
  return fetchJSON<PaginatedUsers>(`/api/admin/users${suffix}`);
};

export const adminApproveUser = (userId: string) =>
  fetchJSON<{ approved: boolean }>(`/api/admin/users/${userId}/approve`, { method: 'PATCH' });

export const adminUnapproveUser = (userId: string) =>
  fetchJSON<{ unapproved: boolean }>(`/api/admin/users/${userId}/unapprove`, { method: 'PATCH' });

// Admin — roles
export const adminAssignRole = (userId: string, roleId: string) =>
  fetchJSON<{ assigned: boolean }>('/api/admin/roles/assign', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, role_id: roleId }),
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

export const adminListRoleCosmetics = (roleId: string) =>
  fetchJSON<{ links: { role_id: string; cosmetic_id: string }[] }>(
    `/api/admin/roles/${encodeURIComponent(roleId)}/cosmetics`,
  );

export const adminLinkRoleCosmetic = (roleId: string, cosmeticId: string) =>
  fetchJSON<{ linked: boolean }>('/api/admin/roles/cosmetics', {
    method: 'POST',
    body: JSON.stringify({ role_id: roleId, cosmetic_id: cosmeticId }),
  });

export const adminUnlinkRoleCosmetic = (roleId: string, cosmeticId: string) =>
  fetchJSON<{ unlinked: boolean }>('/api/admin/roles/cosmetics', {
    method: 'DELETE',
    body: JSON.stringify({ role_id: roleId, cosmetic_id: cosmeticId }),
  });

// Admin — achievements
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

export const adminListTriggers = (achievementId: string) =>
  fetchJSON<{ triggers: AchievementTrigger[] }>(
    `/api/admin/achievements/${encodeURIComponent(achievementId)}/triggers`,
  );

export const adminCreateTrigger = (payload: {
  achievement_id: string; trigger_type: string; trigger_threshold: number;
}) =>
  fetchJSON<{ trigger: AchievementTrigger }>('/api/admin/achievements/triggers', {
    method: 'POST',
    body: JSON.stringify(payload),
  });

export const adminUpdateTrigger = (triggerId: string, patch: Partial<{ trigger_type: string; trigger_threshold: number }>) =>
  fetchJSON<{ updated: boolean }>(`/api/admin/achievements/triggers/${encodeURIComponent(triggerId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
  });

export const adminDeleteTrigger = (triggerId: string) =>
  fetchJSON<{ deleted: boolean }>(`/api/admin/achievements/triggers/${encodeURIComponent(triggerId)}`, { method: 'DELETE' });

export const adminListAchievementCosmetics = (achievementId: string) =>
  fetchJSON<{ links: { achievement_id: string; cosmetic_id: string }[] }>(
    `/api/admin/achievements/${encodeURIComponent(achievementId)}/cosmetics`,
  );

export const adminLinkAchievementCosmetic = (achievementId: string, cosmeticId: string) =>
  fetchJSON<{ linked: boolean }>('/api/admin/achievements/cosmetics', {
    method: 'POST',
    body: JSON.stringify({ achievement_id: achievementId, cosmetic_id: cosmeticId }),
  });

export const adminUnlinkAchievementCosmetic = (achievementId: string, cosmeticId: string) =>
  fetchJSON<{ unlinked: boolean }>('/api/admin/achievements/cosmetics', {
    method: 'DELETE',
    body: JSON.stringify({ achievement_id: achievementId, cosmetic_id: cosmeticId }),
  });

// Admin — cosmetics
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

// Admin — allowlist
export const adminListAllowlist = () =>
  fetchJSON<{ emails: AllowlistEmail[] }>('/api/admin/allowlist');

export const adminApproveAllowlist = (email: string) =>
  fetchJSON<{ email: AllowlistEmail }>('/api/admin/allowlist/approve', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });

export const adminRevokeAllowlist = (email: string) =>
  fetchJSON<{ email: AllowlistEmail }>('/api/admin/allowlist/revoke', {
    method: 'POST',
    body: JSON.stringify({ email }),
  });

// Admin — audit
export const adminAuditLog = (params?: {
  page?: number; page_size?: number; action?: string; target_type?: string; actor_id?: string;
}) => {
  const qp = new URLSearchParams();
  if (params?.page) qp.set('page', String(params.page));
  if (params?.page_size) qp.set('page_size', String(params.page_size));
  if (params?.action) qp.set('action', params.action);
  if (params?.target_type) qp.set('target_type', params.target_type);
  if (params?.actor_id) qp.set('actor_id', params.actor_id);
  const suffix = qp.toString() ? `?${qp.toString()}` : '';
  return fetchJSON<{ entries: AdminAuditEntry[]; total: number; page: number; page_size: number }>(
    `/api/admin/audit${suffix}`,
  );
};

// Admin — analytics
export const adminAnalyticsOverview = () =>
  fetchJSON<AnalyticsOverview>('/api/admin/analytics/overview');

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

/**
 * Read a File as a base64 string (no data-URL prefix). Resolves with
 * just the encoded bytes so the JSON payload is the smallest possible
 * shape the server needs.
 */
function readFileAsBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      // result is a data URL like "data:image/png;base64,iVBORw0K..."
      const result = reader.result as string;
      const comma = result.indexOf(',');
      resolve(comma === -1 ? result : result.slice(comma + 1));
    };
    reader.onerror = () => reject(reader.error || new Error('Failed to read file'));
    reader.readAsDataURL(file);
  });
}

// Mirrors backend/config.py::MAX_AVATAR_SIZE. Kept as a const so the
// guard below doesn't depend on Settings.tsx remembering to check
// size first — every caller of uploadAvatar gets the same protection.
export const MAX_AVATAR_BYTES = 5 * 1024 * 1024;

export const uploadAvatar = async (userId: string, file: File): Promise<{ avatar_url: string }> => {
  if (IS_LOCAL_MODE) return { avatar_url: URL.createObjectURL(file) };
  // Size-check BEFORE the base64 encode. Reading a 50 MB file just to
  // throw it out is wasted CPU + memory. Settings.tsx already
  // pre-checks size for the toast UX, but a future caller (admin
  // bulk tool, recovery script) could easily bypass that and we'd
  // still want the guard.
  if (file.size > MAX_AVATAR_BYTES) {
    throw new Error(
      `That file is ${(file.size / 1024 / 1024).toFixed(1)} MB — max is ${MAX_AVATAR_BYTES / 1024 / 1024} MB.`,
    );
  }
  // POST as JSON+base64 instead of multipart/form-data. The multipart
  // path was silently failing in some browser configurations with
  // `TypeError: Failed to fetch` (no response, request aborted before
  // reaching the server). JSON requests work in every environment
  // that already runs the rest of the profile API successfully, so
  // routing the avatar through the same shape eliminates the failure
  // class entirely.
  const file_b64 = await readFileAsBase64(file);
  return fetchJSON<{ avatar_url: string }>(`/api/profile/${encodeURIComponent(userId)}/avatar`, {
    method: 'POST',
    body: JSON.stringify({ file_b64, content_type: file.type || 'image/png' }),
  });
};

// ── Gradebook ────────────────────────────────────────────────────────────────

export const getGradebookSummary = (userId: string, semester: string) =>
  fetchJSON<GradebookSummary>(
    `/api/gradebook/summary?user_id=${encodeURIComponent(userId)}&semester=${encodeURIComponent(semester)}`,
  );

export const getGradebookCourse = (userId: string, courseId: string) =>
  fetchJSON<GradebookCourse>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}?user_id=${encodeURIComponent(userId)}`,
  );

export const createCategory = (
  userId: string,
  courseId: string,
  name: string,
  weight: number,
) =>
  fetchJSON<{ category: GradeCategory }>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}/categories`,
    { method: 'POST', body: JSON.stringify({ user_id: userId, name, weight }) },
  );

export const bulkUpdateCategories = (
  userId: string,
  courseId: string,
  categories: { id?: string; name: string; weight: number; sort_order: number }[],
) =>
  fetchJSON<{ categories: GradeCategory[] }>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}/categories`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, categories }) },
  );

export const deleteCategory = (userId: string, categoryId: string) =>
  fetchJSON<{ deleted: true }>(
    `/api/gradebook/categories/${encodeURIComponent(categoryId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const createGradedAssignment = (
  userId: string,
  courseId: string,
  fields: Partial<Omit<GradedAssignment, 'id' | 'course_id' | 'source'>> & { title: string },
) =>
  fetchJSON<{ assignment: GradedAssignment }>('/api/gradebook/assignments', {
    method: 'POST',
    body: JSON.stringify({ user_id: userId, course_id: courseId, ...fields }),
  });

export const updateGradedAssignment = (
  userId: string,
  assignmentId: string,
  fields: Partial<Omit<GradedAssignment, 'id' | 'course_id' | 'source'>>,
) =>
  fetchJSON<{ updated: boolean }>(
    `/api/gradebook/assignments/${encodeURIComponent(assignmentId)}`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, ...fields }) },
  );

export const deleteGradedAssignment = (userId: string, assignmentId: string) =>
  fetchJSON<{ deleted: true }>(
    `/api/gradebook/assignments/${encodeURIComponent(assignmentId)}?user_id=${encodeURIComponent(userId)}`,
    { method: 'DELETE' },
  );

export const setLetterScale = (
  userId: string,
  courseId: string,
  scale: LetterScaleTier[] | null,
) =>
  fetchJSON<{ updated: true; letter_scale: LetterScaleTier[] | null }>(
    `/api/gradebook/courses/${encodeURIComponent(courseId)}/scale`,
    { method: 'PATCH', body: JSON.stringify({ user_id: userId, scale }) },
  );

export const applySyllabus = (payload: {
  userId: string;
  courseId: string;
  docId: string;
  categories: { name: string; weight: number; sort_order: number }[];
  assignments: { title: string; due_date: string | null; assignment_type: string | null; notes: string | null }[];
}) =>
  fetchJSON<{ course: GradebookCourse }>('/api/gradebook/syllabus/apply', {
    method: 'POST',
    body: JSON.stringify({
      user_id: payload.userId,
      course_id: payload.courseId,
      doc_id: payload.docId,
      categories: payload.categories,
      assignments: payload.assignments,
    }),
  });

// Typed helper for syllabus uploads — wraps the existing FormData-based
// uploadDocument and narrows the response. Existing callers of uploadDocument
// remain untouched.
export interface UploadSyllabusResponse {
  id: string;
  doc_id?: string;
  category: string;
  summary: string | null;
  categories: ExtractedSyllabusCategory[];
  assignments: { title: string; due_date: string | null; assignment_type: string | null; notes: string | null }[];
}
export const uploadSyllabus = (input: {
  userId: string;
  courseId: string;
  file: File;
}): Promise<UploadSyllabusResponse> => {
  const fd = new FormData();
  fd.append('user_id', input.userId);
  fd.append('course_id', input.courseId);
  fd.append('category', 'syllabus');
  fd.append('file', input.file);
  return uploadDocument(fd);
};
