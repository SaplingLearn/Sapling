"use client";

import React from "react";
import { Icon } from "@/components/Icon";
import { Avatar } from "@/components/Avatar";
import {
  CANDIDATES,
  ROLES,
  DEFAULT_SELECTION,
  type FontRole,
  type FontCandidate,
} from "@/lib/fontLab/candidates";
import { allFontCandidates, stackFor, useGoogleFonts } from "@/lib/fontLab/useGoogleFonts";
import { FONT_LAB_EVENT, FONT_LAB_STORAGE_KEY, readFontLabSelection } from "@/lib/fontLab/navOverride";

type Selection = Record<FontRole, string>;

function loadSelection(): Selection {
  return { ...DEFAULT_SELECTION, ...readFontLabSelection() };
}

function findCandidate(role: FontRole, family: string): FontCandidate {
  return (
    CANDIDATES[role].find((c) => c.family === family) ?? CANDIDATES[role][0]
  );
}

const SIDE_NAV_WIDTH = 232;

const SECTIONS = [
  {
    label: "Learn",
    items: [
      { label: "Dashboard", icon: "home" },
      { label: "Tutor", icon: "brain" },
      { label: "Quiz", icon: "flask" },
      { label: "Tree", icon: "tree" },
    ],
  },
  {
    label: "Organize",
    items: [
      { label: "Library", icon: "book" },
      { label: "Calendar", icon: "cal" },
    ],
  },
];

export function FontLab() {
  const [selection, setSelection] = React.useState<Selection>(DEFAULT_SELECTION);
  const [activeRole, setActiveRole] = React.useState<FontRole>("heading");
  const [hydrated, setHydrated] = React.useState(false);
  const [copied, setCopied] = React.useState(false);

  React.useEffect(() => {
    setSelection(loadSelection());
    setHydrated(true);
  }, []);

  React.useEffect(() => {
    if (!hydrated) return;
    try {
      window.localStorage.setItem(FONT_LAB_STORAGE_KEY, JSON.stringify(selection));
      // `storage` only fires in OTHER tabs, never the one that wrote it — so
      // a dashboard tab open in this same window needs this to pick up the
      // change without a manual reload.
      window.dispatchEvent(new Event(FONT_LAB_EVENT));
    } catch {
      // Best-effort. A design lab losing its scratch state on a private
      // window isn't worth a user-visible error.
    }
  }, [selection, hydrated]);

  const fontsReady = useGoogleFonts(React.useMemo(() => allFontCandidates(), []));

  const active = React.useMemo(
    () => ({
      heading: findCandidate("heading", selection.heading),
      body: findCandidate("body", selection.body),
      label: findCandidate("label", selection.label),
      subtitle: findCandidate("subtitle", selection.subtitle),
    }),
    [selection]
  );

  const isOverridden = React.useMemo(
    () => ROLES.some((role) => selection[role.id] !== DEFAULT_SELECTION[role.id]),
    [selection]
  );

  const stacks = React.useMemo(
    () => ({
      heading: stackFor(active.heading),
      body: stackFor(active.body),
      label: stackFor(active.label),
      subtitle: stackFor(active.subtitle),
    }),
    [active]
  );

  function choose(role: FontRole, family: string) {
    setSelection((s) => ({ ...s, [role]: family }));
  }

  function reset() {
    setSelection(DEFAULT_SELECTION);
  }

  function copyCss() {
    const lines = [
      `--font-heading: ${stacks.heading};`,
      `--font-body: ${stacks.body};`,
      `--font-label: ${stacks.label};`,
      `--font-subtitle: ${stacks.subtitle};`,
    ];
    const text = lines.join("\n");
    navigator.clipboard?.writeText(text).then(
      () => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1600);
      },
      () => {}
    );
  }

  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: `${SIDE_NAV_WIDTH}px 1fr`,
        minHeight: "100vh",
        background: "var(--bg)",
      }}
    >
      <SideNavPreview stacks={stacks} />

      <div style={{ padding: "28px 32px 64px", maxWidth: 980 }}>
        <header style={{ marginBottom: 24 }}>
          <div
            className="label-micro"
            style={{ marginBottom: 8, color: "var(--text-muted)" }}
          >
            Design exploration — not shipped
          </div>
          <h1
            style={{
              fontFamily: "var(--font-display)",
              fontSize: 28,
              fontWeight: 600,
              letterSpacing: "-0.015em",
              color: "var(--text)",
              margin: 0,
            }}
          >
            Font Lab
          </h1>
          <p style={{ fontSize: 14, color: "var(--text-dim)", maxWidth: 640, marginTop: 8, lineHeight: 1.55 }}>
            The rail on the left is a live copy of the dashboard sidebar. Pick
            a face per role below and it updates immediately — mix and match
            until something earns its place next to Sapling&apos;s green.
          </p>
          <p style={{ fontSize: 14, color: "var(--text-dim)", maxWidth: 640, marginTop: 8, lineHeight: 1.55 }}>
            <strong style={{ color: "var(--text)" }}>Your picks also go live on the real dashboard</strong>
            {" "}— open{" "}
            <a href="/dashboard" style={{ color: "var(--brand-forest)" }}>
              /dashboard
            </a>{" "}
            in this browser (same tab or a new one) and the actual SideNav will
            render with whatever you&apos;ve selected here, no code changes
            needed. This only affects your own browser&apos;s localStorage —
            nobody else sees it. Hit &quot;Reset to shipped fonts&quot; to fall
            back to what&apos;s actually deployed.
          </p>
          <div style={{ display: "flex", gap: 8, marginTop: 14, alignItems: "center" }}>
            <button type="button" onClick={copyCss} style={btnStyle(true)}>
              {copied ? "Copied ✓" : "Copy CSS variables"}
            </button>
            <button type="button" onClick={reset} style={btnStyle(false)}>
              Reset to shipped fonts
            </button>
            {isOverridden && (
              <span
                style={{
                  fontSize: 11,
                  fontWeight: 700,
                  letterSpacing: "0.04em",
                  color: "var(--brand-forest)",
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 5,
                }}
              >
                <span
                  aria-hidden
                  style={{ width: 6, height: 6, borderRadius: "50%", background: "var(--brand-forest)" }}
                />
                LIVE on your dashboard
              </span>
            )}
          </div>
          {!fontsReady && (
            <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 10 }}>
              Loading preview faces from Google Fonts…
            </div>
          )}
        </header>

        <nav
          role="tablist"
          aria-label="Font role"
          style={{ display: "flex", gap: 4, borderBottom: "1px solid var(--border)", marginBottom: 20 }}
        >
          {ROLES.map((role) => (
            <button
              key={role.id}
              role="tab"
              aria-selected={activeRole === role.id}
              type="button"
              onClick={() => setActiveRole(role.id)}
              style={{
                padding: "10px 16px",
                fontSize: 13,
                fontWeight: activeRole === role.id ? 600 : 500,
                color: activeRole === role.id ? "var(--text)" : "var(--text-dim)",
                borderBottom: activeRole === role.id ? "2px solid var(--brand-forest)" : "2px solid transparent",
                marginBottom: -1,
                background: "none",
                cursor: "pointer",
              }}
            >
              {role.label}
              <span style={{ marginLeft: 8, fontSize: 11, color: "var(--text-muted)", fontWeight: 400 }}>
                {selection[role.id]}
              </span>
            </button>
          ))}
        </nav>

        <p style={{ fontSize: 13, color: "var(--text-dim)", marginTop: -8, marginBottom: 18 }}>
          {ROLES.find((r) => r.id === activeRole)!.blurb}
        </p>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fill, minmax(280px, 1fr))",
            gap: 10,
          }}
        >
          {CANDIDATES[activeRole].map((c) => {
            const isActive = selection[activeRole] === c.family;
            const stack = stackFor(c);
            return (
              <button
                key={c.family + c.axes}
                type="button"
                onClick={() => choose(activeRole, c.family)}
                style={{
                  textAlign: "left",
                  border: isActive ? "1.5px solid var(--brand-forest)" : "1px solid var(--border)",
                  background: isActive ? "var(--sap-100)" : "var(--bg-subtle)",
                  borderRadius: "var(--r-sm)",
                  padding: "12px 14px",
                  cursor: "pointer",
                  display: "flex",
                  flexDirection: "column",
                  gap: 6,
                  transition: "border-color var(--dur-fast) var(--ease), background var(--dur-fast) var(--ease)",
                }}
              >
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8 }}>
                  <span
                    style={{
                      fontFamily: stack,
                      fontWeight: c.previewWeight,
                      fontStyle: c.italic ? "italic" : "normal",
                      fontSize: 18,
                      color: "var(--text)",
                    }}
                  >
                    {c.family}
                  </span>
                  {c.incumbent && (
                    <span
                      style={{
                        fontSize: 9,
                        letterSpacing: "0.08em",
                        textTransform: "uppercase",
                        color: "var(--brand-forest)",
                        fontWeight: 700,
                        flexShrink: 0,
                      }}
                    >
                      Current
                    </span>
                  )}
                </div>
                <p style={{ fontSize: 11.5, color: "var(--text-dim)", lineHeight: 1.45, margin: 0 }}>{c.note}</p>
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function btnStyle(primary: boolean): React.CSSProperties {
  return {
    padding: "7px 14px",
    fontSize: 12.5,
    fontWeight: 600,
    borderRadius: "var(--r-sm)",
    border: primary ? "1px solid var(--brand-forest)" : "1px solid var(--border)",
    background: primary ? "var(--brand-forest)" : "transparent",
    color: primary ? "#fff" : "var(--text-dim)",
    cursor: "pointer",
  };
}

/**
 * A faithful visual replica of `components/SideNav.tsx`, trimmed to the rows
 * needed to judge type (no auth/pathname wiring — this never renders inside
 * the real shell). Every color/spacing token is pulled from the same
 * `globals.css` variables the real rail uses, so what you see here is what
 * you'd get if the picks above were wired into the live component.
 */
function SideNavPreview({
  stacks,
}: {
  stacks: { heading: string; body: string; label: string; subtitle: string };
}) {
  return (
    <aside
      style={{
        width: SIDE_NAV_WIDTH,
        minWidth: SIDE_NAV_WIDTH,
        height: "100vh",
        position: "sticky",
        top: 0,
        borderRight: "1px solid var(--border)",
        background: "var(--bg-subtle)",
        padding: "16px 10px",
        display: "flex",
        flexDirection: "column",
        gap: 1,
        fontFamily: stacks.body,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          gap: 2,
          padding: "2px 8px 14px",
          borderBottom: "1px solid var(--border)",
          marginBottom: 8,
        }}
      >
        <img
          src="/sapling-icon.svg"
          alt=""
          width={32}
          height={32}
          style={{ width: 32, height: 32, marginTop: -4, marginLeft: -2, marginRight: -4, flexShrink: 0 }}
        />
        <span
          style={{
            fontFamily: stacks.heading,
            fontWeight: 700,
            fontSize: 20,
            color: "var(--brand-forest)",
            letterSpacing: "-0.02em",
            lineHeight: 1.1,
          }}
        >
          Sapling
        </span>
      </div>

      {SECTIONS.map((section, i) => (
        <React.Fragment key={section.label}>
          <div
            style={{
              fontFamily: stacks.label,
              fontSize: 10,
              letterSpacing: "0.14em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              padding: i === 0 ? "20px 10px 10px" : "22px 10px 10px",
            }}
          >
            {section.label}
          </div>
          {section.items.map((item, idx) => (
            <div
              key={item.label}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 10,
                minHeight: 38,
                marginLeft: 10,
                marginRight: 10,
                padding: "6px 12px",
                borderRadius: "var(--r-xs)",
                background: i === 0 && idx === 0 ? "var(--sap-100)" : "transparent",
                color: i === 0 && idx === 0 ? "var(--text)" : "var(--text-dim)",
                fontWeight: i === 0 && idx === 0 ? 600 : 400,
                fontSize: 13,
              }}
            >
              <Icon name={item.icon} size={15} />
              <span style={{ flex: 1 }}>{item.label}</span>
            </div>
          ))}
        </React.Fragment>
      ))}

      <div style={{ flex: 1 }} />

      <div style={{ height: 1, background: "var(--border)", margin: "10px 8px" }} />

      <div style={{ display: "flex", alignItems: "center", gap: 10, padding: "10px 6px 4px" }}>
        <Avatar name="Sam Rivera" size={30} />
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>Sam Rivera</div>
          <div style={{ fontFamily: stacks.subtitle, fontSize: 11, color: "var(--text-muted)" }}>Account</div>
        </div>
      </div>
    </aside>
  );
}
