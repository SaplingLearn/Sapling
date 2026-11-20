"use client";
// A wrapped-up (or legacy) session, read-only (wireframe T14; moved out of
// LoopLearn.tsx unchanged): its transcript and "Start a new session".
import React from "react";
import type { ChatMsg } from "../chat/ChatPanel";

export function ReadOnlyTranscript({ topic, messages, startDisabled, onStart }: {
  topic: string;
  messages: ChatMsg[];
  startDisabled: boolean;
  onStart: () => void;
}) {
  return (
    <div style={{ flex: 1, overflowY: "auto", padding: "20px 32px" }}>
      <div style={{ display: "flex", flexDirection: "column", gap: 14 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <span className="chip">Read-only</span>
          <span style={{ fontSize: 14, color: "var(--text-dim)" }}>
            {topic ? `“${topic}” — ` : ""}an earlier session. Start a new one to keep learning.
          </span>
          <div style={{ flex: 1 }} />
          <button data-testid="loop-readonly-new-session" className="btn btn--primary btn--sm" disabled={startDisabled}
            onClick={onStart}>
            Start a new session
          </button>
        </div>
        <div
          data-testid="loop-readonly-transcript"
          className="card"
          style={{ padding: "var(--pad-lg)", display: "flex", flexDirection: "column", gap: 12 }}
        >
          {messages.length === 0 && (
            <div style={{ fontSize: 13, color: "var(--text-muted)" }}>No messages in this session.</div>
          )}
          {messages.map((m) => (
            <div key={m.id} style={{ alignSelf: m.role === "user" ? "flex-end" : "flex-start", maxWidth: "85%" }}>
              <div className="label-micro" style={{ marginBottom: 2 }}>{m.role === "user" ? "You" : "Tutor"}</div>
              <div
                style={{
                  whiteSpace: "pre-wrap",
                  fontSize: 14,
                  padding: "8px 12px",
                  borderRadius: "var(--r-md)",
                  background: m.role === "user" ? "var(--accent-soft)" : "var(--bg-soft)",
                }}
              >
                {m.content}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
