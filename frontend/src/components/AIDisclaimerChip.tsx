"use client";

import React, { useState } from "react";
import { DisclaimerModal } from "./DisclaimerModal";

export function AIDisclaimerChip() {
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <>
      <div
        style={{ position: "relative" }}
        onMouseEnter={() => setTooltipVisible(true)}
        onMouseLeave={() => setTooltipVisible(false)}
      >
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          aria-label="Review AI guidelines"
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "3px 9px",
            background: "var(--bg-soft)",
            border: "1px solid var(--border)",
            borderRadius: 20,
            cursor: "pointer",
            fontSize: 11,
            color: "var(--text-dim)",
            fontWeight: 500,
            letterSpacing: "0.02em",
          }}
        >
          AI Guidelines
        </button>

        {tooltipVisible && (
          <div
            role="tooltip"
            style={{
              position: "absolute",
              top: "calc(100% + 10px)",
              right: 0,
              background: "var(--bg-panel)",
              border: "1px solid var(--border)",
              borderRadius: "var(--r-md)",
              padding: "13px 15px",
              fontSize: 12,
              lineHeight: 1.6,
              width: 260,
              zIndex: 9999,
              boxShadow: "var(--shadow-md)",
              pointerEvents: "none",
              color: "var(--text-dim)",
            }}
          >
            <div
              className="label-micro"
              style={{ marginBottom: 6, color: "var(--text)" }}
            >
              AI powered learning
            </div>
            <p style={{ margin: "0 0 8px" }}>
              Sapling uses Google Gemini to tutor, quiz, and track your progress.
              Responses may not always be accurate — verify with your course materials.
            </p>
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 8 }}>
              <p style={{ margin: 0, fontSize: 11, color: "var(--text-muted)", lineHeight: 1.5 }}>
                Don&apos;t share passwords or sensitive personal data. Use Sapling as a
                study aid, not a substitute for your own work. Click to review full guidelines.
              </p>
            </div>
          </div>
        )}
      </div>

      <DisclaimerModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
