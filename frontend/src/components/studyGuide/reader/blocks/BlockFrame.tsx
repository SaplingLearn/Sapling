"use client";
import React from "react";

import { Skeleton } from "@/components/Skeleton";

import { useReader } from "../ReaderContext";
import s from "./blocks.module.css";
import { useBlockRegenerate } from "./useBlockRegenerate";

export type BlockTone = "info" | "err" | "accent" | "amber" | "plum";

interface BlockFrameProps {
  blockId: string;
  tone: BlockTone;
  icon: React.ReactNode;
  /** The kind of block, e.g. "Worked example". */
  label: string;
  title?: string;
  /** Controls beside the title, before Regenerate. */
  actions?: React.ReactNode;
  footer?: React.ReactNode;
  /** A check question is never rewritten: its answer is on record. */
  regenerable?: boolean;
  children: React.ReactNode;
}

/** The frame every block shares: icon tile, kind, title, actions, footer. */
export function BlockFrame({
  blockId,
  tone,
  icon,
  label,
  title,
  actions,
  footer,
  regenerable = true,
  children,
}: BlockFrameProps) {
  const { generating } = useReader();
  const { busy, regenerate } = useBlockRegenerate(blockId);
  return (
    <div
      className={s.block}
      data-testid={`guide-block-${blockId}`}
      role="group"
      aria-label={title ? `${label}: ${title}` : label}
    >
      <div className={s.head}>
        <div className={s.heading}>
          <span className={`${s.tile} ${s[tone]}`} aria-hidden="true">
            {icon}
          </span>
          <span className="label-micro">{label}</span>
          {title && <span className={s.title}>{title}</span>}
        </div>
        <div className={s.actions}>
          {!busy && actions}
          {regenerable && !generating && (
            <button
              type="button"
              className={s.regenerate}
              data-testid={`guide-block-regenerate-${blockId}`}
              disabled={busy}
              onClick={regenerate}
            >
              Regenerate
            </button>
          )}
        </div>
      </div>
      {busy ? (
        <div role="status" className={s.regenerating}>
          <Skeleton height={160} radius="var(--r-md)" />
          <span>Regenerating this block. The rest of the guide stays as it is.</span>
        </div>
      ) : (
        <>
          {children}
          {footer && <div className={s.foot}>{footer}</div>}
        </>
      )}
    </div>
  );
}
