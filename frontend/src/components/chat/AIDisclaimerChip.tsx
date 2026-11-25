"use client";

import React, { useState } from "react";
import { AnimatePresence, motion, type Target } from "framer-motion";
import { DisclaimerModal } from "../DisclaimerModal";
import { useMotionPresets } from "@/lib/motion";
import styles from "./AIDisclaimerChip.module.css";

/** The chip's default height, px: the controls it usually sits beside. */
const DEFAULT_CHIP_HEIGHT = 28;

/** `height`: the chip matches the controls beside it (28 by default; the
 *  Tutor's TopBar sets every action to 32). */
export function AIDisclaimerChip({ height = DEFAULT_CHIP_HEIGHT }: { height?: number } = {}) {
  const [tooltipVisible, setTooltipVisible] = useState(false);
  const [modalOpen, setModalOpen] = useState(false);
  const m = useMotionPresets();

  return (
    <>
      <div
        className={styles.wrap}
        onMouseEnter={() => setTooltipVisible(true)}
        onMouseLeave={() => setTooltipVisible(false)}
      >
        <button
          type="button"
          onClick={() => setModalOpen(true)}
          aria-label="Review AI guidelines"
          className={styles.chip}
          style={{ "--chip-h": `${height}px` } as React.CSSProperties}
        >
          <span aria-hidden className={styles.spark}>✦</span>
          AI-assisted
        </button>

        <AnimatePresence>
          {tooltipVisible && (
            <motion.div
              role="tooltip"
              className={styles.tooltip}
              initial={m.scaleIn.initial as Target}
              animate={m.scaleIn.animate}
              exit={m.scaleIn.exit}
              transition={m.scaleIn.transition}
            >
              <div className={`label-micro ${styles.tooltipTitle}`}>
                AI powered learning
              </div>
              <p className={styles.tooltipBody}>
                Sapling uses Anthropic&apos;s Claude to tutor, quiz, and track your progress.
                Responses may not always be accurate — verify with your course materials.
              </p>
              <div className={styles.tooltipFoot}>
                <p className={styles.tooltipNote}>
                  Don&apos;t share passwords or sensitive personal data. Use Sapling as a
                  study aid, not a substitute for your own work. Click to review full guidelines.
                </p>
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>

      <DisclaimerModal open={modalOpen} onClose={() => setModalOpen(false)} />
    </>
  );
}
