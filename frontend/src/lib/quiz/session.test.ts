// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  DISMISSED_KEY,
  QUEUE_COUNT,
  QUEUE_MAX,
  STORAGE_KEY,
  clearDismissed,
  clearSession,
  dismissAttempt,
  isDismissed,
  loadSession,
  persistSession,
  saveSession,
  shouldPersist,
} from "./session";
import { initialSession } from "./machine";
import { DEFAULT_PREFS, FEEDBACK_MODES, loadPrefs, savePrefs } from "./prefs";
import { PREFS_KEY } from "./session";
import type { Phase, QuizConfig, QuizSession } from "./types";

const CONFIG: QuizConfig = {
  num_questions: { min: 1, max: 10, options: [3, 5, 10] },
  difficulties: ["easy", "medium", "hard", "adaptive"],
  question_types: ["multiple_choice"],
};

function session(phase: Phase): QuizSession {
  const base = initialSession({ source: { kind: "tree" }, concept: "c1" }, CONFIG, DEFAULT_PREFS);
  return { ...base, phase, attemptId: "attempt-1" };
}

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("constants", () => {
  it("caps a queued session at get_recommendations' own limit", () => {
    expect(QUEUE_MAX).toBe(5);
    expect(QUEUE_COUNT).toBe(3);
  });
});

describe("saveSession / loadSession", () => {
  it("round-trips a session", () => {
    const s = session("active");
    saveSession(s);
    expect(loadSession()).toEqual(s);
  });

  it("returns null when nothing is stored", () => {
    expect(loadSession()).toBeNull();
  });

  it("returns null for a corrupted record rather than throwing", () => {
    window.localStorage.setItem(STORAGE_KEY, "{not json");
    expect(loadSession()).toBeNull();
  });

  it("returns null for a record that isn't a session", () => {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ hello: "world" }));
    expect(loadSession()).toBeNull();
  });

  it("survives a storage setter that throws (quota, private mode)", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    expect(() => saveSession(session("active"))).not.toThrow();
  });

  it("survives a storage getter that throws", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    expect(loadSession()).toBeNull();
  });

  it("clears", () => {
    saveSession(session("active"));
    clearSession();
    expect(loadSession()).toBeNull();
  });
});

describe("persistSession", () => {
  it("saves from generating onward", () => {
    const persisted: Phase[] = [
      "generating",
      "active",
      "answered",
      "confirm-leave",
      "submitting",
      "paused",
      "error",
    ];
    for (const phase of persisted) {
      expect(shouldPersist(session(phase)), phase).toBe(true);
      window.localStorage.clear();
      persistSession(session(phase));
      expect(loadSession()?.phase, phase).toBe(phase);
    }
  });

  it("does not save on home, configuring or results", () => {
    for (const phase of ["home", "configuring", "results"] as Phase[]) {
      expect(shouldPersist(session(phase)), phase).toBe(false);
      window.localStorage.clear();
      persistSession(session(phase));
      expect(loadSession(), phase).toBeNull();
    }
  });

  it("LEAVES a paused record alone instead of clearing it", () => {
    // The regression the browser lane found: quiz home mounts a fresh
    // `home`-phase session and its config effect persists it, which used to
    // delete the paused attempt the resume strip was about to offer. Storage is
    // cleared at exactly two moments (SUBMITTED and EXIT), both by an explicit
    // `clearSession()` — never as a side effect of a phase.
    const paused = { ...session("paused"), cursor: 2 };
    saveSession(paused);

    for (const phase of ["home", "configuring", "results"] as Phase[]) {
      persistSession(session(phase));
      expect(loadSession(), phase).toEqual(paused);
    }
  });
});

describe("dismissed attempts", () => {
  it("remembers a discard and forgets it on clear", () => {
    expect(isDismissed("a-1")).toBe(false);
    dismissAttempt("a-1");
    expect(isDismissed("a-1")).toBe(true);
    clearDismissed();
    expect(isDismissed("a-1")).toBe(false);
  });

  it("de-duplicates and caps the list", () => {
    dismissAttempt("a-1");
    dismissAttempt("a-1");
    expect(JSON.parse(window.localStorage.getItem(DISMISSED_KEY) as string)).toEqual(["a-1"]);

    for (let i = 0; i < 60; i += 1) dismissAttempt(`x-${i}`);
    const stored = JSON.parse(window.localStorage.getItem(DISMISSED_KEY) as string) as string[];
    expect(stored.length).toBe(50);
    expect(stored[0]).toBe("x-59");
  });

  it("ignores an empty id and a corrupted list", () => {
    dismissAttempt("");
    expect(window.localStorage.getItem(DISMISSED_KEY)).toBeNull();
    window.localStorage.setItem(DISMISSED_KEY, '"nope"');
    expect(isDismissed("a-1")).toBe(false);
  });
});

describe("prefs", () => {
  it("has exactly the two feedback modes and nothing else hardcoded", () => {
    expect(FEEDBACK_MODES).toEqual(["as-you-go", "at-end"]);
  });

  it("defaults to no remembered count/difficulty and at-end feedback", () => {
    expect(loadPrefs()).toEqual({ count: null, difficulty: null, feedback: "at-end" });
  });

  it("round-trips", () => {
    savePrefs({ count: 10, difficulty: "hard", feedback: "as-you-go" });
    expect(loadPrefs()).toEqual({ count: 10, difficulty: "hard", feedback: "as-you-go" });
  });

  it("drops a remembered value the live config no longer offers", () => {
    savePrefs({ count: 15, difficulty: "impossible", feedback: "as-you-go" });
    expect(loadPrefs(CONFIG)).toEqual({ count: null, difficulty: null, feedback: "as-you-go" });
    // Without a config to check against, the stored value is left alone.
    expect(loadPrefs()).toEqual({ count: 15, difficulty: "impossible", feedback: "as-you-go" });
  });

  it("keeps a remembered value the config still offers", () => {
    savePrefs({ count: 3, difficulty: "adaptive", feedback: "at-end" });
    expect(loadPrefs(CONFIG)).toEqual({ count: 3, difficulty: "adaptive", feedback: "at-end" });
  });

  it("falls back for a corrupted or hostile record", () => {
    window.localStorage.setItem(PREFS_KEY, "{not json");
    expect(loadPrefs()).toEqual(DEFAULT_PREFS);
    window.localStorage.setItem(PREFS_KEY, JSON.stringify({ count: "five", feedback: "psychic" }));
    expect(loadPrefs()).toEqual(DEFAULT_PREFS);
  });
});
