"use client";

import React, { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { CustomSelect } from "./CustomSelect";
import { useToast } from "./ToastProvider";
import { generateQuiz, submitQuiz } from "@/lib/api";

type Phase = "select" | "active" | "review" | "results";

interface ConceptOption {
  id: string;
  name: string;
  course_id?: string | null;
  course_code?: string | null;
}

interface QuizQuestion {
  id: number | string;
  question: string;
  options: { label: string; text: string; correct: boolean }[];
  explanation: string;
  concept_tested: string;
  difficulty: string;
}

interface QuizAnswer {
  question_id: number | string;
  selected: string;
}

interface QuizResult {
  question_id: number | string;
  selected: string;
  correct: boolean;
  correct_answer: string;
  explanation: string;
}

interface QuizPanelProps {
  userId: string;
  concepts: ConceptOption[];
  initialConceptId?: string | null;
  onExit: () => void;
}

const COUNT_OPTIONS = [
  { value: "5", label: "5 questions" },
  { value: "10", label: "10 questions" },
  { value: "15", label: "15 questions" },
];

const DIFFICULTY_OPTIONS = [
  { value: "easy", label: "Easy" },
  { value: "medium", label: "Medium" },
  { value: "hard", label: "Hard" },
  { value: "adaptive", label: "Adaptive" },
];

export function QuizPanel({ userId, concepts, initialConceptId, onExit }: QuizPanelProps) {
  const router = useRouter();
  const toast = useToast();

  const [phase, setPhase] = useState<Phase>("select");
  const [conceptId, setConceptId] = useState<string | null>(initialConceptId ?? concepts[0]?.id ?? null);
  const [count, setCount] = useState("5");
  const [difficulty, setDifficulty] = useState("medium");

  const [quizId, setQuizId] = useState<string | null>(null);
  const [questions, setQuestions] = useState<QuizQuestion[]>([]);
  const [answers, setAnswers] = useState<QuizAnswer[]>([]);
  const [qIndex, setQIndex] = useState(0);
  const [currentSelection, setCurrentSelection] = useState<string | null>(null);
  const [lastCorrect, setLastCorrect] = useState<boolean | null>(null);

  const [results, setResults] = useState<{ score: number; total: number; results: QuizResult[]; mastery_before: number; mastery_after: number } | null>(null);
  const [loading, setLoading] = useState(false);

  const currentQuestion = questions[qIndex];

  const start = async () => {
    if (!conceptId) {
      toast.warn("Pick a concept first.");
      return;
    }
    setLoading(true);
    try {
      const res = await generateQuiz(userId, conceptId, Number(count), difficulty);
      setQuizId(res.quiz_id);
      setQuestions(res.questions || []);
      setAnswers([]);
      setQIndex(0);
      setCurrentSelection(null);
      setLastCorrect(null);
      setPhase("active");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to generate quiz.");
    } finally {
      setLoading(false);
    }
  };

  const submitCurrent = () => {
    if (!currentQuestion || !currentSelection) return;
    const chosen = currentQuestion.options.find(o => o.label === currentSelection);
    setLastCorrect(!!chosen?.correct);
    setAnswers(a => [...a, { question_id: currentQuestion.id, selected: currentSelection }]);
    setPhase("review");
  };

  const next = () => {
    if (qIndex + 1 >= questions.length) {
      finish();
      return;
    }
    setQIndex(i => i + 1);
    setCurrentSelection(null);
    setLastCorrect(null);
    setPhase("active");
  };

  const finish = async () => {
    if (!quizId) return;
    setLoading(true);
    try {
      const res = await submitQuiz(quizId, answers);
      setResults(res);
      setPhase("results");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to submit quiz.");
    } finally {
      setLoading(false);
    }
  };

  const retake = () => {
    setPhase("select");
    setResults(null);
  };

  const explainConcept = (concept: string) => {
    router.push(`/learn?topic=${encodeURIComponent(concept)}&mode=socratic`);
  };

  const conceptOptions = useMemo(
    () => concepts.map(c => ({
      value: c.id,
      label: c.course_code ? `${c.course_code} — ${c.name}` : c.name,
    })),
    [concepts],
  );

  return (
    <div
      className="card"
      style={{
        padding: "var(--pad-xl)",
        display: "flex",
        flexDirection: "column",
        gap: 18,
        maxWidth: 680,
      }}
    >
      {phase === "select" && (
        <>
          <div>
            <div className="label-micro" style={{ marginBottom: 4 }}>Quiz</div>
            <div className="h-serif" style={{ fontSize: 24 }}>Test what you know</div>
          </div>
          <div>
            <div className="label-micro" style={{ marginBottom: 6 }}>Concept</div>
            {concepts.length === 0 ? (
              <div style={{ fontSize: 13, color: "var(--text-muted)" }}>No concepts yet — learn something first.</div>
            ) : (
              <CustomSelect<string>
                value={conceptId ?? ""}
                options={conceptOptions}
                onChange={v => setConceptId(v)}
                style={{ width: "100%" }}
                placeholder="Pick a concept…"
              />
            )}
          </div>
          <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
            <div style={{ flex: 1, minWidth: 160 }}>
              <div className="label-micro" style={{ marginBottom: 6 }}>Count</div>
              <CustomSelect value={count} options={COUNT_OPTIONS} onChange={setCount} style={{ width: "100%" }} />
            </div>
            <div style={{ flex: 1, minWidth: 160 }}>
              <div className="label-micro" style={{ marginBottom: 6 }}>Difficulty</div>
              <CustomSelect value={difficulty} options={DIFFICULTY_OPTIONS} onChange={setDifficulty} style={{ width: "100%" }} />
            </div>
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <button className="btn" onClick={onExit}>Cancel</button>
            <button className="btn btn--primary" onClick={start} disabled={loading || !conceptId}>
              {loading ? "Generating…" : "Start quiz"}
            </button>
          </div>
        </>
      )}

      {phase === "active" && currentQuestion && (
        <>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
            <div className="label-micro">Question {qIndex + 1} of {questions.length}</div>
            <div className="chip" style={{ textTransform: "uppercase" }}>{currentQuestion.difficulty}</div>
          </div>
          <div style={{ fontSize: 16, lineHeight: 1.55 }}>{currentQuestion.question}</div>
          <div role="radiogroup" aria-label="Answer choices" style={{ display: "grid", gap: 8 }}>
            {currentQuestion.options.map(o => {
              const selected = currentSelection === o.label;
              return (
                <button
                  key={o.label}
                  role="radio"
                  aria-checked={selected}
                  onClick={() => setCurrentSelection(o.label)}
                  style={{
                    textAlign: "left",
                    padding: "10px 14px",
                    border: `1.5px solid ${selected ? "var(--accent)" : "var(--border)"}`,
                    background: selected ? "var(--accent-soft)" : "var(--bg-panel)",
                    color: selected ? "var(--accent)" : "var(--text)",
                    borderRadius: "var(--r-md)",
                    fontSize: 14,
                  }}
                >
                  <span className="mono" style={{ marginRight: 8, fontWeight: 600 }}>{o.label}.</span>
                  {o.text}
                </button>
              );
            })}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <button className="btn" onClick={onExit}>Exit</button>
            <button className="btn btn--primary" onClick={submitCurrent} disabled={!currentSelection}>
              Submit answer
            </button>
          </div>
        </>
      )}

      {phase === "review" && currentQuestion && (
        <>
          <div className="label-micro">Review</div>
          <div
            style={{
              padding: "10px 14px",
              borderRadius: "var(--r-md)",
              background: lastCorrect ? "var(--accent-soft)" : "var(--err-soft)",
              color: lastCorrect ? "var(--accent)" : "var(--err)",
              fontSize: 14,
              fontWeight: 500,
            }}
          >
            {lastCorrect ? "Correct." : "Not quite."}
          </div>
          <div style={{ fontSize: 15, lineHeight: 1.55 }}>{currentQuestion.question}</div>
          <div style={{ display: "grid", gap: 6 }}>
            {currentQuestion.options.map(o => {
              const picked = currentSelection === o.label;
              const right = o.correct;
              const bg = right ? "var(--accent-soft)" : picked ? "var(--err-soft)" : "var(--bg-subtle)";
              const color = right ? "var(--accent)" : picked ? "var(--err)" : "var(--text-dim)";
              return (
                <div
                  key={o.label}
                  style={{
                    padding: "9px 12px",
                    borderRadius: "var(--r-sm)",
                    background: bg,
                    color,
                    fontSize: 13,
                    display: "flex",
                    gap: 8,
                    alignItems: "center",
                  }}
                >
                  <span className="mono" style={{ fontWeight: 600 }}>{o.label}.</span>
                  <span style={{ flex: 1 }}>{o.text}</span>
                  {right && <span aria-hidden>✓</span>}
                  {!right && picked && <span aria-hidden>✗</span>}
                </div>
              );
            })}
          </div>
          <div
            style={{
              padding: 12,
              background: "var(--bg-subtle)",
              borderRadius: "var(--r-sm)",
              fontSize: 13,
              color: "var(--text-dim)",
              lineHeight: 1.55,
            }}
          >
            {currentQuestion.explanation}
          </div>
          <div style={{ display: "flex", justifyContent: "space-between" }}>
            <button className="btn" onClick={() => explainConcept(currentQuestion.concept_tested)}>
              Explain this
            </button>
            <button className="btn btn--primary" onClick={next}>
              {qIndex + 1 >= questions.length ? "See results" : "Next question"}
            </button>
          </div>
        </>
      )}

      {phase === "results" && results && (
        <>
          <div className="label-micro">Results</div>
          <div className="h-serif" style={{ fontSize: 32 }}>
            {Math.round((results.score / Math.max(1, results.total)) * 100)}%
          </div>
          <div style={{ fontSize: 13, color: "var(--text-dim)" }}>
            {results.score} / {results.total} correct · mastery{" "}
            <span style={{ color: results.mastery_after >= results.mastery_before ? "var(--accent)" : "var(--err)", fontWeight: 600 }}>
              {Math.round(results.mastery_before * 100)}% → {Math.round(results.mastery_after * 100)}%
            </span>
          </div>
          <div style={{ display: "flex", gap: 8, justifyContent: "flex-end" }}>
            <button className="btn" onClick={retake}>Retake</button>
            <button className="btn btn--primary" onClick={onExit}>Done</button>
          </div>
        </>
      )}
    </div>
  );
}
