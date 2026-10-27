"use client";

import React, { useState } from "react";

/**
 * The entire user-facing surface of the course-scope signal.
 *
 * The tutor used to narrate this: "I don't have anything from your syllabus
 * about that." That sentence was usually false (the course covers it; we
 * just hadn't indexed it), useless to a student who asked to learn rather
 * than audit our corpus, and it taught them that questions beyond the
 * uploaded PDFs were off-limits. The backend now forbids the model from
 * mentioning coverage at all (COVERAGE_PROMPT_RULE) and labels the turn
 * itself instead — `topic_status` on the chat response / stream `done`
 * event.
 *
 * This renders that label and nothing else: no explanation in the reply, no
 * warning, no action. It shows ONLY for an established `new` verdict —
 * `unknown` means the backend could not tell, and a chip there would assert
 * a novelty nobody established.
 */
export function NewTopicChip({ topic }: { topic?: string }) {
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const label = topic?.trim()
    ? `“${topic.trim()}” is new to this course — added to your knowledge map.`
    : "This is new to your course — added to your knowledge map.";

  return (
    <div
      style={{ position: "relative", display: "inline-flex" }}
      onMouseEnter={() => setTooltipVisible(true)}
      onMouseLeave={() => setTooltipVisible(false)}
    >
      <span
        data-testid="tutor-new-topic"
        title={label}
        aria-label={label}
        style={{
          display: "inline-flex",
          alignItems: "center",
          gap: 4,
          height: 28,
          padding: "0 10px",
          background: "var(--bg-subtle)",
          border: "1px dashed var(--border)",
          borderRadius: "var(--r-full)",
          fontSize: 12,
          fontWeight: 500,
          letterSpacing: "0.02em",
          lineHeight: 1.2,
          color: "var(--text-dim)",
          whiteSpace: "nowrap",
        }}
      >
        <span aria-hidden style={{ fontSize: 10, opacity: 0.85 }}>✦</span>
        New
      </span>

      {tooltipVisible && (
        <div
          role="tooltip"
          style={{
            position: "absolute",
            top: "calc(100% + 8px)",
            right: 0,
            width: 240,
            padding: "8px 10px",
            background: "var(--bg)",
            border: "1px solid var(--border)",
            borderRadius: "var(--r-sm)",
            boxShadow: "var(--shadow-md)",
            fontSize: 12,
            lineHeight: 1.45,
            color: "var(--text-dim)",
            zIndex: 20,
          }}
        >
          {label}
        </div>
      )}
    </div>
  );
}
