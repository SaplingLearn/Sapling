"use client";
// A wrapped-up (or legacy) session, read-only (wireframe T14; moved out of
// LoopLearn.tsx unchanged): its transcript and "Start a new session".
import { LEARNING_COPY } from "@/lib/learningCopy";
import React from "react";
import type { ChatMsg } from "../chat/ChatPanel";
import styles from "./ReadOnlyTranscript.module.css";

export function ReadOnlyTranscript({ topic, messages, startDisabled, onStart }: {
  topic: string;
  messages: ChatMsg[];
  startDisabled: boolean;
  onStart: () => void;
}) {
  return (
    <div className={styles.scroll}>
      <div className={styles.stack}>
        <div className={styles.bar}>
          <span className="chip">Read-only</span>
          <span className={styles.lede}>
            {topic ? `“${topic}” — ` : ""}an earlier session. Start a new one to keep learning.
          </span>
          <div className={styles.spacer} />
          <button data-testid="loop-readonly-new-session" className="btn btn--primary btn--sm" disabled={startDisabled}
            onClick={onStart}>
            {LEARNING_COPY.newSession}
          </button>
        </div>
        <div
          data-testid="loop-readonly-transcript"
          className={`card ${styles.transcript}`}
        >
          {messages.length === 0 && (
            <div className={styles.empty}>No messages in this session.</div>
          )}
          {messages.map((m) => (
            <div key={m.id} className={m.role === "user" ? `${styles.turn} ${styles.turnUser}` : styles.turn}>
              <div className={`label-micro ${styles.who}`}>{m.role === "user" ? "You" : "Tutor"}</div>
              <div className={styles.bubble}>{m.content}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
