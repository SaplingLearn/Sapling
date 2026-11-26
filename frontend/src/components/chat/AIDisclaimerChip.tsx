"use client";

import React, { useState } from "react";
import { DisclaimerModal } from "../DisclaimerModal";

export function AIDisclaimerChip() {
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);

  return (
    <>
      <div
        className="relative"
        onMouseEnter={() => setTooltipVisible(true)}
        onMouseLeave={() => setTooltipVisible(false)}
      >
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          aria-label="Review AI guidelines"
          className="inline-flex items-center gap-1 h-7 py-0 px-3 bg-bg-subtle border border-border rounded-[var(--r-full)] cursor-pointer text-sm text-text-dim font-medium tracking-[0.02em] leading-[1.2]"
        >
          <span aria-hidden className="text-2xs opacity-85">✦</span>
          AI-assisted
        </button>

        {tooltipVisible && (
          <div
            role="tooltip"
            className="absolute top-[calc(100%_+_10px)] right-0 bg-bg-panel border border-border rounded-md py-[13px] px-[15px] text-sm leading-[1.6] w-65 z-9999 shadow-md pointer-events-none text-text-dim"
          >
            <div
              className="label-micro mb-1.5 text-text"
            >
              AI powered learning
            </div>
            <p className="mt-0 mx-0 mb-2">
              Sapling uses Anthropic&apos;s Claude to tutor, quiz, and track your progress.
              Responses may not always be accurate — verify with your course materials.
            </p>
            <div className="border-t border-t-border pt-2">
              <p className="m-0 text-xs text-text-muted leading-[1.5]">
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
