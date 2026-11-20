"use client";
import React from "react";
import { PageTurn } from "../chat/ChatPanel";

/** One tutor turn outside the chat log (the check-in opener, the plan's intro),
 *  on the page as the conversation's turns are (`PageTurn`). */
export function TutorTurn({ children, testId }: { children: React.ReactNode; testId?: string }) {
  return <PageTurn plain testId={testId}>{children}</PageTurn>;
}
