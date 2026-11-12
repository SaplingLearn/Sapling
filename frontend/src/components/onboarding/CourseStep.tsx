"use client";

/**
 * The courses screen: the student's year, a catalog search, the courses they
 * picked, and a way on for a student whose courses aren't in the catalog.
 */
import React, { useEffect, useState } from "react";
import { onboardingCoursesSearch, type OnboardingCourse } from "@/lib/api";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { YEARS } from "./flow";
import { ScreenHead } from "./ScreenHead";

type SearchStatus = "loading" | "ok" | "error";

/** What the always-present status line reads out after each search. */
function statusLine(status: SearchStatus, count: number): string {
  if (status === "error") return "The course search didn't work.";
  if (status === "loading") return "";
  return count === 0 ? "No courses match." : `${count} course${count === 1 ? "" : "s"} found.`;
}

function useCourseSearch(query: string) {
  const [results, setResults] = useState<OnboardingCourse[]>([]);
  const [status, setStatus] = useState<SearchStatus>("loading");
  const [attempt, setAttempt] = useState(0);
  // Latest query wins (#802/#769, as in ManageCoursesModal). The debounce only
  // stops a search that hasn't been SENT: a student who pauses after "cs"
  // fires that broad search, and if it lands after "cs 111" it replaces the
  // right results with twenty unrelated courses.
  const searchReq = useLatestRequest();

  useEffect(() => {
    const run = searchReq.begin();
    const t = setTimeout(() => {
      onboardingCoursesSearch(query.trim())
        .then(r => {
          if (!run.isCurrent()) return;
          setResults(r.courses ?? []);
          setStatus("ok");
        })
        .catch(() => {
          // Said as a failure with a retry, never as "no matches".
          if (!run.isCurrent()) return;
          setResults([]);
          setStatus("error");
        });
    }, 200);
    return () => {
      clearTimeout(t);
      searchReq.cancel();
    };
  }, [query, attempt, searchReq]);

  const retry = () => {
    setStatus("loading");
    setAttempt(a => a + 1);
  };
  return { results, status, retry };
}

export function CourseStep({ year, courses, later, notice, onYear, onCourses, onLater }: {
  year: string;
  courses: OnboardingCourse[];
  later: boolean;
  notice?: React.ReactNode;
  onYear: (v: string) => void;
  onCourses: (v: OnboardingCourse[]) => void;
  onLater: () => void;
}) {
  const [query, setQuery] = useState("");
  const { results, status, retry } = useCourseSearch(query);
  const picked = new Set(courses.map(c => c.id));
  const toggle = (c: OnboardingCourse) =>
    onCourses(picked.has(c.id) ? courses.filter(x => x.id !== c.id) : [...courses, c]);

  // Enter picks the top result rather than leaving the screen (the flow's own
  // Enter-for-Next skips a key a control has already used).
  const onSearchKey = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const first = results[0];
    if (first && !picked.has(first.id)) toggle(first);
  };

  return (
    <section className="ob-screen">
      <ScreenHead
        title="What are you taking this term?"
        sub="Pick your year and add your courses. Each one grows its own branch."
        notice={notice}
      />
      <div className="ob-courses">
        <div className="ob-label" id="ob-year-label">Your year</div>
        <div className="ob-years" role="group" aria-labelledby="ob-year-label">
          {YEARS.map(([v, l]) => (
            <button key={v} data-testid={`onboarding-year-${v}`} className="ob-choice" aria-pressed={year === v} onClick={() => onYear(v)}>
              {l}
            </button>
          ))}
        </div>
        <div className="ob-label ob-label--gap">Your courses</div>
        {/* One box: the search field and its results read as a single control. */}
        <div className="ob-search">
          <input
            data-testid="onboarding-course-search"
            className="ob-input ob-input--search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={onSearchKey}
            aria-label="Search courses"
            placeholder="Search by code or name, like CS 111"
          />
          <div className="ob-results">
            {results.map(c => {
              const added = picked.has(c.id);
              return (
                <button
                  key={c.id}
                  data-testid={`onboarding-course-result-${c.id}`}
                  className="ob-result"
                  aria-pressed={added}
                  onClick={() => toggle(c)}
                >
                  <span className="ob-result-code">{c.course_code}</span>
                  <span className="ob-result-name">{c.course_name}</span>
                  <span className="ob-result-action">{added ? "Added ✓" : "Add"}</span>
                </button>
              );
            })}
            {status === "error" && (
              <div className="ob-empty" data-testid="onboarding-course-search-error">
                We couldn&apos;t search the course list.{" "}
                <button data-testid="onboarding-course-search-retry" className="ob-textlink" onClick={retry}>
                  Try again
                </button>
              </div>
            )}
            {status === "ok" && results.length === 0 && (
              <div className="ob-empty" data-testid="onboarding-course-search-empty">
                No courses match. Try the code, like &quot;MA 123&quot;.
              </div>
            )}
          </div>
        </div>
        <p className="ob-sr-only" aria-live="polite" data-testid="onboarding-course-search-status">
          {statusLine(status, results.length)}
        </p>
        {courses.length > 0 && (
          <div className="ob-chips">
            {courses.map(c => (
              <button
                key={c.id}
                data-testid={`onboarding-course-remove-${c.id}`}
                className="ob-chip"
                aria-label={`Remove ${c.course_code}`}
                onClick={() => toggle(c)}
              >
                {c.course_code}<span aria-hidden="true">×</span>
              </button>
            ))}
          </div>
        )}
        <button data-testid="onboarding-courses-later" className="ob-textlink ob-later" aria-pressed={later} onClick={onLater}>
          My courses aren&apos;t listed — I&apos;ll add them later
        </button>
        <div aria-live="polite">
          {later && (
            <p className="ob-note" data-testid="onboarding-courses-later-note">
              You can add your courses from the dashboard once you&apos;re set up.
            </p>
          )}
        </div>
      </div>
    </section>
  );
}
