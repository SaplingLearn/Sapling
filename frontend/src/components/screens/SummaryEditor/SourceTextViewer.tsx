"use client";
import React from "react";
import type { AskReference } from "@/lib/types";

export interface SourceTextViewerProps {
  text: string;
  onReference: (reference: AskReference) => void;
}

export function SourceTextViewer({ text, onReference }: SourceTextViewerProps) {
  const handleMouseUp = () => {
    const selected = window.getSelection()?.toString() ?? "";
    if (selected.trim()) {
      onReference({ kind: "text", text: selected });
    }
  };

  return (
    <div
      data-testid="summary-editor-source-text"
      className="body-serif"
      style={{ padding: 24, overflowY: "auto", height: "100%", userSelect: "text", whiteSpace: "pre-wrap" }}
      onMouseUp={handleMouseUp}
    >
      {text}
    </div>
  );
}
