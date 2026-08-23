"use client";

import React, { useEffect, useRef, useState } from "react";
import { useUser } from "@/context/UserContext";
import { fetchSettings, updateSettings } from "@/lib/api";
import type { UserSettings } from "@/lib/types";

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
      style={{ position: "relative", display: "inline-block" }}
      onMouseEnter={() => setTooltip(true)}
      onMouseLeave={() => setTooltip(false)}
      onFocus={() => setTooltip(true)}
      onBlur={() => setTooltip(false)}
    >
      <button
        role="switch"
        aria-checked={enabled}
        onClick={() => onChange(!enabled)}
        className="btn btn--sm"
        style={{
          padding: "5px 10px",
          background: enabled ? "var(--accent-soft)" : "var(--bg-subtle)",
          color: enabled ? "var(--accent)" : "var(--text-dim)",
          borderColor: enabled ? "var(--accent-border)" : "var(--border)",
          fontSize: 12,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
        }}
      >
        <span
          aria-hidden
          style={{
            width: 24,
            height: 12,
            borderRadius: "var(--r-full)",
            background: enabled ? "var(--accent)" : "var(--border-strong)",
            position: "relative",
            transition: "background var(--dur-fast) var(--ease)",
          }}
        >
          <span
            style={{
              position: "absolute",
              top: 1,
              left: enabled ? 13 : 1,
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#fff",
              transition: "left var(--dur-fast) var(--ease)",
            }}
          />
        </span>
        Class intel
      </button>
      {tooltip && (
        <div
          role="tooltip"
          style={{
            position: "absolute",
            top: "calc(100% + 6px)",
            ...(align === "left" ? { left: 0 } : { right: 0 }),
            zIndex: 60,
            width: 240,
            padding: 10,
            background: "var(--bg-panel)",
            border: "1px solid var(--border-strong)",
            borderRadius: "var(--r-md)",
            boxShadow: "var(--shadow-md)",
            fontSize: 11,
            color: "var(--text-dim)",
            lineHeight: 1.5,
          }}
        >
          <strong style={{ color: "var(--text)", display: "block", marginBottom: 4 }}>
            Shared course context
          </strong>
          Includes anonymized class-level patterns (common gaps, frequent questions). Disabling keeps the
          tutor focused on only your individual state.
        </div>
      )}
    </div>
  );
}
