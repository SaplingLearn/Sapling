// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import { clearOnboardingIntent, isOnboardingIntentScopeValid, ONBOARDING_INTENT_TTL_MS, readOnboardingIntent, recordOnboardingSession, writeOnboardingIntent } from "./onboardingHandoff";

const scope = { userId: "student-1", courseId: "course-1", goal: { text: "Trace recursion", target_node_ids: ["node-1"] } };
beforeEach(() => { sessionStorage.clear(); localStorage.clear(); vi.restoreAllMocks(); });

describe("onboarding learning intent", () => {
  it("keeps an explicit confirmed goal in this account and course only", () => {
    expect(writeOnboardingIntent(scope)).toBe(true);
    expect(readOnboardingIntent("student-1", "course-1")?.goal).toEqual(scope.goal);
    expect(readOnboardingIntent("student-2", "course-1")).toBeNull();
    expect(readOnboardingIntent("student-1", "course-2")).toBeNull();
    expect(readOnboardingIntent("student-1", "course-1")?.goal).toEqual(scope.goal);
  });

  it("represents whole-course exploration without inventing goal targets", () => {
    expect(writeOnboardingIntent({ ...scope, goal: null })).toBe(true);
    expect(readOnboardingIntent(scope.userId, scope.courseId)?.goal).toBeNull();
  });

  it("rejects empty, duplicated, over-12 targets and objectives over 500 characters", () => {
    for (const goal of [
      { text: "", target_node_ids: [] },
      { text: "", target_node_ids: ["node-1", "node-1"] },
      { text: "", target_node_ids: Array.from({ length: 13 }, (_, i) => `node-${i}`) },
      { text: "a".repeat(501), target_node_ids: ["node-1"] },
      { text: "", target_node_ids: [" "] },
    ]) expect(writeOnboardingIntent({ ...scope, goal })).toBe(false);
    expect(writeOnboardingIntent({ ...scope, goal: { text: "a".repeat(500), target_node_ids: Array.from({ length: 12 }, (_, i) => `node-${i}`) } })).toBe(true);
  });

  it("ignores stale, unknown-version, malformed and cross-account stored records", () => {
    writeOnboardingIntent(scope);
    const key = sessionStorage.key(0)!;
    const original = JSON.parse(sessionStorage.getItem(key)!);
    for (const invalid of [
      { ...original, createdAt: Date.now() - ONBOARDING_INTENT_TTL_MS },
      { ...original, createdAt: Date.now() + 120_000 },
      { ...original, version: 2 },
      { ...original, userId: "student-2" },
      { ...original, goal: { text: "", target_node_ids: "node-1" } },
    ]) {
      sessionStorage.setItem(key, JSON.stringify(invalid));
      expect(readOnboardingIntent(scope.userId, scope.courseId)).toBeNull();
    }
    sessionStorage.setItem(key, "not-json");
    expect(readOnboardingIntent(scope.userId, scope.courseId)).toBeNull();
  });

  it("does not consume a newer Begin click when an earlier operation settles", () => {
    writeOnboardingIntent(scope);
    const earlier = readOnboardingIntent(scope.userId, scope.courseId)!;
    writeOnboardingIntent({ ...scope, goal: null });
    clearOnboardingIntent(earlier);
    const newer = readOnboardingIntent(scope.userId, scope.courseId)!;
    expect(newer).toBeTruthy();
    expect(newer.goal).toBeNull();
    clearOnboardingIntent(newer);
    expect(readOnboardingIntent(scope.userId, scope.courseId)).toBeNull();
  });

  it("records the accepted lazy opener without consuming the pending goal", () => {
    writeOnboardingIntent(scope);
    const intent = readOnboardingIntent(scope.userId, scope.courseId)!;
    expect(recordOnboardingSession(intent, "session-1")?.startedSessionId).toBe("session-1");
    expect(readOnboardingIntent(scope.userId, scope.courseId)?.goal).toEqual(scope.goal);
    writeOnboardingIntent({ ...scope, goal: null });
    expect(recordOnboardingSession(intent, "late-session")).toBeNull();
    expect(readOnboardingIntent(scope.userId, scope.courseId)?.startedSessionId).toBeUndefined();
  });

  it("reports unavailable storage without pretending the goal was handed off", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new DOMException("Unavailable", "SecurityError"); });
    expect(writeOnboardingIntent(scope)).toBe(false);
  });

  it("clears only the completed checkpoint tagged by this exact Begin click", () => {
    writeOnboardingIntent(scope);
    const intent = readOnboardingIntent(scope.userId, scope.courseId)!;
    const key = `sapling_onboarding_v3:${scope.userId}`;
    const otherKey = "sapling_onboarding_v3:another-user";
    localStorage.setItem(key, JSON.stringify({ version: 3, userId: scope.userId, handoffId: intent.id }));
    localStorage.setItem(otherKey, "another-account-checkpoint");
    clearOnboardingIntent(intent);
    expect(localStorage.getItem(key)).toBeNull();
    expect(localStorage.getItem(otherKey)).toBe("another-account-checkpoint");
  });

  it.each([
    { version: 3, userId: scope.userId, handoffId: "newer-begin" },
    { version: 4, userId: scope.userId },
    { version: 3, userId: "another-user" },
  ])("keeps a revised or differently owned checkpoint after successful start: %j", (checkpoint) => {
    writeOnboardingIntent(scope);
    const intent = readOnboardingIntent(scope.userId, scope.courseId)!;
    const key = `sapling_onboarding_v3:${scope.userId}`;
    const raw = JSON.stringify(checkpoint);
    localStorage.setItem(key, raw);
    clearOnboardingIntent(intent);
    expect(localStorage.getItem(key)).toBe(raw);
  });

  it("requires fresh enrollment and every explicit non-root concept from the chosen course", () => {
    writeOnboardingIntent(scope);
    const intent = readOnboardingIntent(scope.userId, scope.courseId)!;
    const validNode = { id: "node-1", course_id: "course-1", is_subject_root: false };
    expect(isOnboardingIntentScopeValid(intent, scope.userId, scope.courseId, [scope.courseId], [validNode])).toBe(true);
    expect(isOnboardingIntentScopeValid(intent, "student-2", scope.courseId, [scope.courseId], [validNode])).toBe(false);
    expect(isOnboardingIntentScopeValid(intent, scope.userId, "course-2", [scope.courseId], [validNode])).toBe(false);
    expect(isOnboardingIntentScopeValid(intent, scope.userId, scope.courseId, [], [validNode])).toBe(false);
    expect(isOnboardingIntentScopeValid(intent, scope.userId, scope.courseId, [scope.courseId], [{ ...validNode, course_id: "course-2" }])).toBe(false);
    expect(isOnboardingIntentScopeValid(intent, scope.userId, scope.courseId, [scope.courseId], [{ ...validNode, is_subject_root: true }])).toBe(false);
    expect(isOnboardingIntentScopeValid(intent, scope.userId, scope.courseId, [scope.courseId], [{ ...validNode, mastery_tier: "subject_root" }])).toBe(false);
    expect(isOnboardingIntentScopeValid(intent, scope.userId, scope.courseId, [scope.courseId], [])).toBe(false);
  });
});
