"use client";

import React, { useEffect, useRef, useState } from "react";
import { useUser } from "@/context/UserContext";
import { fetchSettings, updateSettings } from "@/lib/api";
import type { UserSettings } from "@/lib/types";
import { cn } from "@/lib/cn";

const STORAGE_KEY = "sapling_shared_ctx";

// user_settings.share_class_context (migration 0037): the persisted form of
// this toggle, enforced server-side at the class-aggregation write chokepoint
// (#72). Not yet part of the UserSettings type in lib/types.ts, so widen it
// locally.
type ShareClassContextSettings = Partial<UserSettings> & {
  share_class_context?: boolean;
};

export function useSharedContext(): [boolean, (v: boolean) => void] {
  const { userId, userReady } = useUser();
  const [enabled, setEnabled] = useState(true);
  // Once the user toggles locally, a late-arriving server hydration must not
  // clobber their fresh choice.
  const dirtyRef = useRef(false);

  useEffect(() => {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw === "false") setEnabled(false);
  }, []);

  // Best-effort server hydration (#72): the preference persists on
  // user_settings so it follows the user across devices and gates the WRITE
  // path server-side. On any failure — offline, signed out, or a server that
  // does not serve the column yet — the localStorage value above stands.
  useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    fetchSettings(userId)
      .then((settings) => {
        if (cancelled || dirtyRef.current) return;
        const server = (settings as ShareClassContextSettings).share_class_context;
        if (typeof server === "boolean") {
          setEnabled(server);
          localStorage.setItem(STORAGE_KEY, String(server));
        }
      })
      .catch(() => {
        /* keep the localStorage value */
      });
    return () => {
      cancelled = true;
    };
  }, [userReady, userId]);

  const update = (v: boolean) => {
    dirtyRef.current = true;
    setEnabled(v);
    localStorage.setItem(STORAGE_KEY, String(v));
    // Best-effort write-through (#72). Swallow failures: the local toggle
    // still gates this client's read path when offline or when the server
    // does not accept the field yet.
    if (userId) {
      const patch: ShareClassContextSettings = { share_class_context: v };
      updateSettings(userId, patch).catch((err) => {
        console.warn(
          "Failed to persist share_class_context; toggle applied locally only",
          err,
        );
      });
    }
  };
  return [enabled, update];
}

export function SharedContextToggle({
  enabled,
  onChange,
  align = "right",
}: {
  enabled: boolean;
  onChange: (v: boolean) => void;
  /**
   * Which edge of the button the tooltip is anchored to. The tooltip is 240px
   * wide against a ~130px button, so the unanchored side always overhangs —
   * anchoring must match where the toggle sits in its container or the panel
   * renders off-card and gets clipped (#581).
   *
   * "right" (default) suits a toggle flush against the RIGHT edge of its
   * container, e.g. the active-session TopBar actions. "left" suits one flush
   * against the LEFT edge, e.g. the start-session card's space-between row.
   */
  align?: "left" | "right";
}) {
  const [tooltip, setTooltip] = useState(false);

  return (
    <div
      className="relative inline-block"
      onMouseEnter={() => setTooltip(true)}
      onMouseLeave={() => setTooltip(false)}
      onFocus={() => setTooltip(true)}
      onBlur={() => setTooltip(false)}
    >
      <button
        role="switch"
        aria-checked={enabled}
        onClick={() => onChange(!enabled)}
        className={cn("btn btn--sm", "py-[5px] px-2.5 text-sm inline-flex items-center gap-1.5", enabled ? "bg-accent-soft" : "bg-bg-subtle", enabled ? "text-accent" : "text-text-dim", enabled ? "border-accent-border" : "border-border")}
      >
        <span
          aria-hidden
          className={cn("w-6 h-3 rounded-[var(--r-full)] relative [transition:background_var(--dur-fast)_var(--ease)]", enabled ? "bg-accent" : "bg-border-strong")}
        >
          <span
            className={cn("absolute top-px w-2.5 h-2.5 rounded-[50%] bg-accent-fg [transition:left_var(--dur-fast)_var(--ease)]", enabled ? "left-[13px]" : "left-px")}
          />
        </span>
        Class intel
      </button>
      {tooltip && (
        <div
          role="tooltip"
          className="absolute top-[calc(100%_+_6px)] z-60 w-60 p-2.5 [background:var(--bg-panel)] border border-border-strong rounded-md shadow-md text-xs text-text-dim leading-[1.5]" style={{ ...(align === "left" ? { left: 0 } : { right: 0 }) }}
        >
          <strong className="text-text block mb-1">
            Shared course context
          </strong>
          Includes anonymized class-level patterns (common gaps, frequent questions). Disabling keeps the
          tutor focused on only your individual state.
        </div>
      )}
    </div>
  );
}
