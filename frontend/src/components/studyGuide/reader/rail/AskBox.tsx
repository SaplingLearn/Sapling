"use client";
import React from "react";

import { Icon } from "@/components/Icon";

import { useReader } from "../ReaderContext";
import { tutorQuestion } from "../readerModel";
import s from "./rail.module.css";

/** A question about the guide, sent to the tutor with the guide's outline. */
export function AskBox() {
  const { guide, askTutor, tutorBusy } = useReader();
  const [question, setQuestion] = React.useState("");
  const inputId = React.useId();
  const asked = question.trim();

  const send = (event: React.FormEvent) => {
    event.preventDefault();
    if (asked) void askTutor(guide.content.title, tutorQuestion(guide, asked));
  };

  return (
    <form className={s.ask} onSubmit={send}>
      <label htmlFor={inputId} className={s.askLabel}>
        <Icon name="clover" size={16} />
        Ask about this guide
      </label>
      <div className={s.askRow}>
        <input
          id={inputId}
          type="text"
          className="field"
          data-testid="guide-ask-input"
          placeholder="Ask a question"
          value={question}
          onChange={event => setQuestion(event.target.value)}
        />
        <button
          type="submit"
          className={`btn btn--primary ${s.askSend}`}
          data-testid="guide-ask-send"
          aria-label="Send to tutor"
          disabled={!asked || tutorBusy}
        >
          <Icon name="send" size={15} />
        </button>
      </div>
      {tutorBusy && (
        <span role="status" className={s.askStatus}>
          Opening the tutor with this guide as context
        </span>
      )}
    </form>
  );
}
