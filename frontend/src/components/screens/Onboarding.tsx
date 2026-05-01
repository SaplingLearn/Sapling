"use client";

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { useUser } from "@/context/UserContext";
import { useToast } from "@/components/ToastProvider";
import { CustomSelect } from "@/components/CustomSelect";
import { Icon } from "@/components/Icon";
import {
  onboardingCoursesSearch,
  submitOnboardingProfile,
  type OnboardingCourse,
  type OnboardingProfilePayload,
} from "@/lib/api";

type LearningStyleId = OnboardingProfilePayload["learning_style"];

const YEARS = ["freshman", "sophomore", "junior", "senior", "graduate", "other"] as const;

// Real Icon names (from components/Icon.tsx), not decorative dingbats.
// Dingbats look clever but carry no shared meaning; icons do.
const LEARNING_STYLES: { id: LearningStyleId; title: string; description: string; icon: string }[] = [
  { id: "visual",   title: "Visual",          description: "I learn best through diagrams, graphs, and visuals.",             icon: "tree" },
  { id: "reading",  title: "Reading/Writing", description: "I prefer text — notes, explanations, and written practice.",     icon: "book" },
  { id: "auditory", title: "Auditory",        description: "I absorb material best when I hear or discuss it.",              icon: "users" },
  { id: "hands-on", title: "Hands-on",        description: "I learn by doing — exercises, labs, and practical application.", icon: "flask" },
  { id: "mixed",    title: "A mix of all",    description: "I learn best through a blend of modes.",                          icon: "sparkle" },
];

const DRAFT_KEY = "sapling_onboarding_draft";

interface Draft {
  first_name: string;
  last_name: string;
  school: string;
  year: string;
  majors: string[];
  minors: string[];
  course_ids: string[];
  course_cache: OnboardingCourse[];
  learning_style: LearningStyleId | null;
  step: number;
}

const EMPTY_DRAFT: Draft = {
  first_name: "",
  last_name: "",
  school: "Boston University",
  year: "",
  majors: [],
  minors: [],
  course_ids: [],
  course_cache: [],
  learning_style: null,
  step: 0,
};

function loadDraft(): Draft {
  if (typeof window === "undefined") return EMPTY_DRAFT;
  try {
    const raw = localStorage.getItem(DRAFT_KEY);
    if (!raw) return EMPTY_DRAFT;
    const parsed = JSON.parse(raw);
    return { ...EMPTY_DRAFT, ...parsed };
  } catch {
    return EMPTY_DRAFT;
  }
}

const STEP_COUNT = 6;

export function Onboarding() {
  const router = useRouter();
  const { userId, userName, userReady, isAuthenticated, signOut } = useUser();
  const toast = useToast();

  const [draft, setDraft] = useState<Draft>(EMPTY_DRAFT);
  const [hydrated, setHydrated] = useState(false);
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    const d = loadDraft();
    const [first, ...rest] = (userName || "").split(" ");
    setDraft(prev => ({
      ...d,
      first_name: d.first_name || first || prev.first_name,
      last_name: d.last_name || rest.join(" ") || prev.last_name,
    }));
    setHydrated(true);
  }, [userName]);

  useEffect(() => {
    if (!hydrated) return;
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify(draft)); } catch {}
  }, [draft, hydrated]);

  useEffect(() => {
    if (!userReady) return;
    if (!isAuthenticated) router.replace("/auth");
  }, [userReady, isAuthenticated, router]);

  const setField = useCallback(<K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft(prev => ({ ...prev, [key]: value }));
  }, []);

  const next = useCallback(() => {
    setDraft(prev => ({ ...prev, step: Math.min(prev.step + 1, STEP_COUNT - 1) }));
  }, []);

  const back = useCallback(() => {
    setDraft(prev => ({ ...prev, step: Math.max(prev.step - 1, 0) }));
  }, []);

  const close = useCallback(async () => {
    await signOut();
    router.replace("/auth");
  }, [signOut, router]);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [close]);

  const canContinue = useMemo(() => {
    switch (draft.step) {
      case 0: return true;
      case 1: return draft.first_name.trim().length > 0 && draft.last_name.trim().length > 0;
      case 2: return draft.school.trim().length > 0 && draft.year.length > 0;
      case 3: return draft.majors.length > 0;
      case 4: return draft.course_ids.length > 0;
      case 5: return draft.learning_style !== null;
      default: return false;
    }
  }, [draft]);

  const finish = useCallback(async () => {
    if (!userId || !draft.learning_style) return;
    setSubmitting(true);
    try {
      await submitOnboardingProfile({
        user_id: userId,
        first_name: draft.first_name.trim(),
        last_name: draft.last_name.trim(),
        year: draft.year,
        majors: draft.majors,
        minors: draft.minors,
        course_ids: draft.course_ids,
        learning_style: draft.learning_style,
      });
      localStorage.removeItem(DRAFT_KEY);
      toast.success("Welcome to Sapling!");
      router.replace("/dashboard");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to save profile. Please try again.");
    } finally {
      setSubmitting(false);
    }
  }, [userId, draft, toast, router]);

  return (
    <div
      style={{
        minHeight: "100vh",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        background: "radial-gradient(ellipse at top, var(--accent-soft) 0%, var(--bg) 60%)",
        padding: "40px 20px",
      }}
    >
      <div
        className="card"
        style={{
          position: "relative",
          width: "min(560px, 100%)",
          padding: "40px 36px",
        }}
      >
        <button
          className="btn btn--ghost btn--sm"
          aria-label="Close onboarding"
          onClick={close}
          style={{ position: "absolute", top: 12, right: 12 }}
        >
          ×
        </button>

        <div style={{ display: "flex", gap: 6, justifyContent: "center", marginBottom: 24 }}>
          {Array.from({ length: STEP_COUNT }).map((_, i) => (
            <div
              key={i}
              style={{
                width: i === draft.step ? 28 : 8,
                height: 6,
                borderRadius: "var(--r-full)",
                background: i <= draft.step ? "var(--accent)" : "var(--bg-soft)",
                transition: "all var(--dur) var(--ease)",
              }}
            />
          ))}
        </div>

        {draft.step === 0 && <StepWelcome />}
        {draft.step === 1 && (
          <StepName
            firstName={draft.first_name}
            lastName={draft.last_name}
            onFirst={v => setField("first_name", v)}
            onLast={v => setField("last_name", v)}
          />
        )}
        {draft.step === 2 && (
          <StepSchool
            school={draft.school}
            year={draft.year}
            onSchool={v => setField("school", v)}
            onYear={v => setField("year", v)}
          />
        )}
        {draft.step === 3 && (
          <StepAcademics
            majors={draft.majors}
            minors={draft.minors}
            onMajors={v => setField("majors", v)}
            onMinors={v => setField("minors", v)}
          />
        )}
        {draft.step === 4 && (
          <StepCourses
            selectedIds={draft.course_ids}
            selectedCache={draft.course_cache}
            onSelect={(ids, cache) => setDraft(prev => ({ ...prev, course_ids: ids, course_cache: cache }))}
          />
        )}
        {draft.step === 5 && (
          <StepLearningStyle
            value={draft.learning_style}
            onChange={v => setField("learning_style", v)}
          />
        )}

        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 32 }}>
          {draft.step > 0 && (
            <button className="btn" onClick={back} disabled={submitting}>
              Back
            </button>
          )}
          <button
            className="btn btn--primary"
            disabled={!canContinue || submitting}
            onClick={draft.step === STEP_COUNT - 1 ? finish : next}
            style={{ minWidth: 130, justifyContent: "center" }}
          >
            {submitting ? "Saving…" : draft.step === STEP_COUNT - 1 ? "Enter Sapling →" : "Continue"}
          </button>
        </div>
      </div>
    </div>
  );
}

function StepWelcome() {
  return (
    <div style={{ textAlign: "center" }}>
      <div className="h-serif" style={{ fontSize: 32, fontWeight: 500, marginBottom: 10 }}>
        Welcome to Sapling
      </div>
      <div style={{ fontSize: 14, color: "var(--text-dim)", lineHeight: 1.55, maxWidth: 440, margin: "0 auto" }}>
        Let&apos;s set up your learning space. A few quick questions so the AI tutor can meet you where you are.
      </div>
    </div>
  );
}

function FieldLabel({ children }: { children: React.ReactNode }) {
  return <div className="label-micro" style={{ marginBottom: 6 }}>{children}</div>;
}

function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  const { style, ...rest } = props;
  return (
    <input
      {...rest}
      style={{
        width: "100%",
        padding: "10px 12px",
        fontSize: 14,
        border: "1px solid var(--border)",
        borderRadius: "var(--r-sm)",
        background: "var(--bg-input)",
        color: "var(--text)",
        ...style,
      }}
    />
  );
}

function StepName({ firstName, lastName, onFirst, onLast }: {
  firstName: string; lastName: string;
  onFirst: (v: string) => void; onLast: (v: string) => void;
}) {
  return (
    <div>
      <div className="h-serif" style={{ fontSize: 26, fontWeight: 500, marginBottom: 6 }}>What should we call you?</div>
      <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 18 }}>This is the name shown to study partners.</div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <div>
          <FieldLabel>First name</FieldLabel>
          <TextInput value={firstName} onChange={e => onFirst(e.target.value)} placeholder="Jose" autoFocus />
        </div>
        <div>
          <FieldLabel>Last name</FieldLabel>
          <TextInput value={lastName} onChange={e => onLast(e.target.value)} placeholder="Cruz" />
        </div>
      </div>
    </div>
  );
}

function StepSchool({ school, year, onSchool, onYear }: {
  school: string; year: string;
  onSchool: (v: string) => void; onYear: (v: string) => void;
}) {
  return (
    <div>
      <div className="h-serif" style={{ fontSize: 26, fontWeight: 500, marginBottom: 6 }}>Where are you studying?</div>
      <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 18 }}>Sapling is currently limited to Boston University.</div>
      <FieldLabel>School</FieldLabel>
      <TextInput value={school} onChange={e => onSchool(e.target.value)} disabled style={{ marginBottom: 16 }} />
      <FieldLabel>Year</FieldLabel>
      <CustomSelect<string>
        value={year}
        placeholder="Select your year…"
        options={YEARS.map(y => ({ value: y, label: y.charAt(0).toUpperCase() + y.slice(1) }))}
        onChange={onYear}
        style={{ width: "100%" }}
      />
    </div>
  );
}

function StepAcademics({ majors, minors, onMajors, onMinors }: {
  majors: string[]; minors: string[];
  onMajors: (v: string[]) => void; onMinors: (v: string[]) => void;
}) {
  return (
    <div>
      <div className="h-serif" style={{ fontSize: 26, fontWeight: 500, marginBottom: 6 }}>Your academic focus</div>
      <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 18 }}>Add at least one major. Minors are optional.</div>
      <FieldLabel>Majors</FieldLabel>
      <TagInput values={majors} onChange={onMajors} placeholder="e.g. Computer Science" />
      <div style={{ height: 14 }} />
      <FieldLabel>Minors</FieldLabel>
      <TagInput values={minors} onChange={onMinors} placeholder="e.g. Philosophy" />
    </div>
  );
}

function TagInput({ values, onChange, placeholder }: {
  values: string[]; onChange: (v: string[]) => void; placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = () => {
    const v = draft.trim();
    if (!v || values.includes(v)) return;
    onChange([...values, v]);
    setDraft("");
  };
  const remove = (v: string) => onChange(values.filter(x => x !== v));
  return (
    <div>
      <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: values.length ? 8 : 0 }}>
        {values.map(v => (
          <span
            key={v}
            className="chip"
            style={{ textTransform: "none", fontFamily: "var(--font-sans)", background: "var(--accent-soft)", color: "var(--accent)", borderColor: "var(--accent-border)" }}
          >
            {v}
            <button onClick={() => remove(v)} aria-label={`Remove ${v}`} style={{ color: "inherit", fontSize: 13, lineHeight: 1, marginLeft: 2 }}>
              ×
            </button>
          </span>
        ))}
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <TextInput
          value={draft}
          onChange={e => setDraft(e.target.value)}
          onKeyDown={e => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
        />
        <button className="btn" onClick={add} disabled={!draft.trim()}>Add</button>
      </div>
    </div>
  );
}

function StepCourses({ selectedIds, selectedCache, onSelect }: {
  selectedIds: string[];
  selectedCache: OnboardingCourse[];
  onSelect: (ids: string[], cache: OnboardingCourse[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<OnboardingCourse[]>([]);
  const [loading, setLoading] = useState(false);
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      setLoading(true);
      onboardingCoursesSearch(query)
        .then(r => setResults(r.courses ?? []))
        .catch(() => setResults([]))
        .finally(() => setLoading(false));
    }, 200);
    return () => { if (debounceRef.current) clearTimeout(debounceRef.current); };
  }, [query]);

  const cacheMap = useMemo(() => new Map(selectedCache.map(c => [c.id, c])), [selectedCache]);

  const toggle = (course: OnboardingCourse) => {
    const exists = selectedIds.includes(course.id);
    if (exists) {
      onSelect(
        selectedIds.filter(id => id !== course.id),
        selectedCache.filter(c => c.id !== course.id),
      );
    } else {
      onSelect([...selectedIds, course.id], [...selectedCache, course]);
    }
  };

  return (
    <div>
      <div className="h-serif" style={{ fontSize: 26, fontWeight: 500, marginBottom: 6 }}>What are you studying?</div>
      <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 18 }}>
        Pick a few courses to seed your knowledge tree. You can always add more later.
      </div>
      <TextInput
        value={query}
        onChange={e => setQuery(e.target.value)}
        placeholder="Search by code or name (e.g. CS 131)"
        autoFocus
      />
      {selectedCache.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginTop: 12 }}>
          {selectedCache.map(c => (
            <span
              key={c.id}
              className="chip"
              style={{ textTransform: "none", fontFamily: "var(--font-sans)", background: "var(--accent-soft)", color: "var(--accent)", borderColor: "var(--accent-border)" }}
            >
              {c.course_code}
              <button onClick={() => toggle(c)} aria-label={`Remove ${c.course_code}`} style={{ color: "inherit", fontSize: 13, lineHeight: 1, marginLeft: 2 }}>×</button>
            </span>
          ))}
        </div>
      )}
      <div style={{ marginTop: 14, maxHeight: 260, overflowY: "auto", border: "1px solid var(--border)", borderRadius: "var(--r-sm)" }}>
        {loading && <div style={{ padding: "14px 12px", fontSize: 12, color: "var(--text-muted)" }}>Searching…</div>}
        {!loading && results.length === 0 && (
          <div style={{ padding: "14px 12px", fontSize: 12, color: "var(--text-muted)" }}>No courses match.</div>
        )}
        {!loading && results.map(c => {
          const selected = selectedIds.includes(c.id) || cacheMap.has(c.id);
          return (
            <button
              key={c.id}
              onClick={() => toggle(c)}
              style={{
                width: "100%",
                padding: "10px 12px",
                fontSize: 13,
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                gap: 10,
                background: selected ? "var(--accent-soft)" : "transparent",
                color: selected ? "var(--accent)" : "var(--text)",
                borderBottom: "1px solid var(--border)",
                textAlign: "left",
              }}
            >
              <span>
                <span style={{ fontWeight: 600 }}>{c.course_code}</span>
                <span style={{ color: "var(--text-dim)", marginLeft: 8 }}>{c.course_name}</span>
              </span>
              {selected && <span>✓</span>}
            </button>
          );
        })}
      </div>
    </div>
  );
}

function StepLearningStyle({ value, onChange }: {
  value: LearningStyleId | null;
  onChange: (v: LearningStyleId) => void;
}) {
  return (
    <div>
      <div className="h-serif" style={{ fontSize: 26, fontWeight: 500, marginBottom: 6 }}>How do you learn best?</div>
      <div style={{ fontSize: 13, color: "var(--text-dim)", marginBottom: 18 }}>
        The AI tutor adjusts its tone and pacing to match.
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
        {LEARNING_STYLES.map(s => {
          const selected = value === s.id;
          return (
            <button
              key={s.id}
              role="radio"
              aria-checked={selected}
              onClick={() => onChange(s.id)}
              style={{
                padding: "14px 14px",
                border: `1.5px solid ${selected ? "var(--accent)" : "var(--border)"}`,
                background: selected ? "var(--accent-soft)" : "var(--bg-panel)",
                borderRadius: "var(--r-md)",
                textAlign: "left",
                transition: "all var(--dur-fast) var(--ease)",
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 4 }}>
                <span style={{ color: selected ? "var(--accent)" : "var(--text-dim)", display: "inline-flex" }}>
                  <Icon name={s.icon} size={16} />
                </span>
                <span style={{ fontWeight: 600, fontSize: 14, color: selected ? "var(--accent)" : "var(--text)" }}>{s.title}</span>
              </div>
              <div style={{ fontSize: 11, color: "var(--text-dim)", lineHeight: 1.4 }}>{s.description}</div>
            </button>
          );
        })}
      </div>
    </div>
  );
}
