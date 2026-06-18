"use client";
import React from "react";
import { createPortal } from "react-dom";
import {
  getGradescopeStatus,
  saveGradescopeCredentials,
  connectGradescopeViaBuSso,
  listGradescopeCourses,
  listGradescopeLinks,
  linkGradescopeCourse,
  syncGradescopeCourse,
  deleteGradescopeCredentials,
  type GradescopeCourse,
  type GradescopeSyncResult,
} from "@/lib/api";

interface Props {
  open: boolean;
  userId: string;
  /** Course id to link + sync. Omit for the settings-page "manage connection
   *  only" flow — the modal will skip link/sync and stop at "connected". */
  saplingCourseId?: string;
  /** Pretty label shown in the kicker. Defaults to "Gradescope" when no
   *  course is provided (settings mode). */
  saplingCourseLabel?: string;
  onClose: () => void;
  /** Fired after a successful sync. Not called in settings/connect-only mode. */
  onSynced?: () => void;
}

type Stage =
  | "loading"
  | "choose-mode"
  | "credentials"
  | "cookies"
  | "bu-sso-form"
  | "bu-sso-waiting"
  | "connected" // settings-mode: creds saved, no course to sync
  | "link"
  | "ready"
  | "syncing"
  | "done";

export function GradescopeSyncModal({
  open,
  userId,
  saplingCourseId,
  saplingCourseLabel,
  onClose,
  onSynced,
}: Props) {
  const [mounted, setMounted] = React.useState(false);
  const [stage, setStage] = React.useState<Stage>("loading");
  const [error, setError] = React.useState<string | null>(null);
  const [lastSyncedAt, setLastSyncedAt] = React.useState<string | null>(null);

  // Credentials form
  const [email, setEmail] = React.useState("");
  const [password, setPassword] = React.useState("");

  // Cookie-paste form
  const [gradescopeSession, setGradescopeSession] = React.useState("");
  const [signedToken, setSignedToken] = React.useState("");

  // BU SSO form
  const [buUsername, setBuUsername] = React.useState("");
  const [buPassword, setBuPassword] = React.useState("");

  // Linking
  const [courses, setCourses] = React.useState<GradescopeCourse[]>([]);
  const [linkedGsCourseId, setLinkedGsCourseId] = React.useState<string | null>(null);

  // Sync result
  const [result, setResult] = React.useState<GradescopeSyncResult | null>(null);

  React.useEffect(() => setMounted(true), []);

  const refreshState = React.useCallback(async () => {
    setError(null);
    setStage("loading");
    try {
      const status = await getGradescopeStatus(userId);
      setLastSyncedAt(status.last_synced_at);
      if (!status.has_credentials) {
        // No saved creds — let the user pick how they want to connect.
        setStage("choose-mode");
        return;
      }
      // Settings-mode (no course): we're done at "connected" once creds
      // are saved — there's no course to link or sync from here.
      if (!saplingCourseId) {
        setStage("connected");
        return;
      }
      const links = await listGradescopeLinks(userId);
      const myLink = links.links.find((l) => l.sapling_course_id === saplingCourseId);
      if (myLink) {
        setLinkedGsCourseId(myLink.gradescope_course_id);
        setStage("ready");
      } else {
        const gs = await listGradescopeCourses(userId);
        setCourses(gs.courses);
        setStage("link");
      }
    } catch (e: any) {
      setError(e?.message ?? "Couldn't load Gradescope status");
      setStage("choose-mode");
    }
  }, [userId, saplingCourseId]);

  React.useEffect(() => {
    if (!open) return;
    setResult(null);
    setError(null);
    setEmail("");
    setPassword("");
    setGradescopeSession("");
    setSignedToken("");
    setBuUsername("");
    setBuPassword("");
    refreshState();
  }, [open, refreshState]);

  if (!mounted || !open) return null;

  async function onSubmitCredentials(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    try {
      await saveGradescopeCredentials(userId, {
        auth_mode: "password",
        email: email.trim(),
        password,
      });
      setPassword("");
      await refreshState();
    } catch (e: any) {
      const msg = (e?.message ?? "").toString();
      setError(msg.includes("Invalid") ? "Invalid Gradescope credentials." : msg);
    }
  }

  async function onSubmitBuSso(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const username = buUsername.trim();
    if (!username || !buPassword) {
      setError("Enter your BU username and password.");
      return;
    }
    // Move to "waiting for Duo" stage immediately so the user knows
    // their phone is about to buzz. The fetch promise stays open for up
    // to ~125s while Playwright drives the SSO + Duo flow on the server.
    setStage("bu-sso-waiting");
    try {
      await connectGradescopeViaBuSso(userId, username, buPassword, 120);
      // Clear the password from memory as soon as we don't need it.
      setBuPassword("");
      setBuUsername("");
      await refreshState();
    } catch (e: any) {
      const msg = (e?.message ?? "").toString();
      setBuPassword(""); // never leave a wrong password sitting in state
      if (/408|duo.*timeout|wasn.?t approved/i.test(msg)) {
        setError(
          "Duo push wasn't approved in time. Tap Approve quickly when your phone buzzes.",
        );
      } else if (/login failed|incorrect|invalid/i.test(msg)) {
        setError("BU login failed. Username or password is incorrect.");
      } else if (/denied|declined|rejected/i.test(msg)) {
        setError("Duo push was denied. Try again and tap Approve.");
      } else if (/captcha/i.test(msg)) {
        setError(
          "BU asked for a CAPTCHA. The automated flow can't solve those. Use the cookie-paste option instead.",
        );
      } else {
        setError(msg || "SSO failed unexpectedly.");
      }
      setStage("bu-sso-form");
    }
  }

  async function onSubmitCookies(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    const session = gradescopeSession.trim();
    if (!session) {
      setError("Paste your _gradescope_session cookie value.");
      return;
    }
    try {
      await saveGradescopeCredentials(userId, {
        auth_mode: "cookies",
        gradescope_session: session,
        signed_token: signedToken.trim() || undefined,
      });
      setGradescopeSession("");
      setSignedToken("");
      await refreshState();
    } catch (e: any) {
      const msg = (e?.message ?? "").toString();
      setError(
        msg.includes("expired") || msg.includes("invalid")
          ? "Those cookies didn't authenticate. Copy them again from a freshly signed-in tab."
          : msg,
      );
    }
  }

  async function onPickCourse(gsCourseId: string) {
    setError(null);
    try {
      await linkGradescopeCourse(userId, saplingCourseId, gsCourseId);
      setLinkedGsCourseId(gsCourseId);
      setStage("ready");
    } catch (e: any) {
      setError(e?.message ?? "Couldn't link course");
    }
  }

  async function onSyncNow() {
    if (!saplingCourseId) return; // settings-only mode has no course to sync
    setError(null);
    setStage("syncing");
    try {
      const res = await syncGradescopeCourse(userId, saplingCourseId);
      setResult(res);
      setStage("done");
      onSynced?.();
    } catch (e: any) {
      setError(e?.message ?? "Sync failed");
      setStage("ready");
    }
  }

  async function onResetCredentials() {
    if (!window.confirm("Remove your Gradescope credentials? You'll need to re-enter them to sync again.")) return;
    try {
      await deleteGradescopeCredentials(userId);
      setLinkedGsCourseId(null);
      setStage("choose-mode");
    } catch (e: any) {
      setError(e?.message ?? "Couldn't remove credentials");
    }
  }

  return createPortal(
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="gs-modal-title"
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(15, 17, 16, 0.55)",
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
        zIndex: 100,
        padding: 16,
      }}
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: "var(--bg-panel)",
          borderRadius: "var(--r-lg)",
          padding: "28px 32px",
          width: "min(560px, 100%)",
          maxHeight: "min(640px, 90vh)",
          display: "flex",
          flexDirection: "column",
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <header style={{ marginBottom: 18 }}>
          <div
            className="mono"
            style={{
              fontSize: 10,
              letterSpacing: "0.18em",
              textTransform: "uppercase",
              color: "var(--text-muted)",
              marginBottom: 8,
            }}
          >
            Gradescope · {saplingCourseLabel || "Connection"}
          </div>
          <h2
            id="gs-modal-title"
            style={{
              fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
              fontWeight: 500,
              fontSize: 24,
              letterSpacing: "-0.01em",
              color: "var(--text)",
              margin: 0,
            }}
          >
            {stage === "choose-mode"
              ? "Connect Gradescope"
              : stage === "credentials"
                ? "Sign in with Gradescope password"
                : stage === "cookies"
                  ? "Paste your Gradescope session"
                  : stage === "bu-sso-form"
                    ? "Sign in with BU SSO"
                    : stage === "bu-sso-waiting"
                      ? "Waiting for Duo approval"
                      : stage === "connected"
                        ? "Gradescope is connected"
                        : stage === "link"
                          ? "Pick the matching Gradescope course"
                          : stage === "done"
                            ? "Sync complete"
                            : "Pull grades from Gradescope"}
          </h2>
        </header>

        {error && (
          <div
            role="alert"
            style={{
              padding: "10px 12px",
              borderRadius: "var(--r-sm)",
              background: "var(--err-soft)",
              color: "var(--err)",
              fontSize: 13,
              marginBottom: 14,
              border: "1px solid color-mix(in oklab, var(--err) 25%, transparent)",
            }}
          >
            {error}
          </div>
        )}

        <div style={{ flex: 1, overflowY: "auto", minHeight: 0 }}>
          {stage === "loading" && (
            <p style={{ color: "var(--text-dim)", fontSize: 14 }}>Loading…</p>
          )}

          {stage === "choose-mode" && (
            <ChooseModeStep
              onPickPassword={() => {
                setError(null);
                setStage("credentials");
              }}
              onPickCookies={() => {
                setError(null);
                setStage("cookies");
              }}
              onPickBuSso={() => {
                setError(null);
                setStage("bu-sso-form");
              }}
              onCancel={onClose}
            />
          )}

          {stage === "bu-sso-form" && (
            <BuSsoFormStep
              username={buUsername}
              password={buPassword}
              setUsername={setBuUsername}
              setPassword={setBuPassword}
              onSubmit={onSubmitBuSso}
              onBack={() => {
                setError(null);
                setStage("choose-mode");
              }}
            />
          )}

          {stage === "bu-sso-waiting" && <BuSsoWaitingStep />}

          {stage === "cookies" && (
            <CookiePasteStep
              gradescopeSession={gradescopeSession}
              signedToken={signedToken}
              setGradescopeSession={setGradescopeSession}
              setSignedToken={setSignedToken}
              onSubmit={onSubmitCookies}
              onBack={() => {
                setError(null);
                setStage("choose-mode");
              }}
            />
          )}

          {stage === "credentials" && (
            <form onSubmit={onSubmitCredentials}>
              <p
                style={{
                  fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
                  fontSize: 14,
                  lineHeight: 1.6,
                  color: "var(--text-dim)",
                  margin: "0 0 18px",
                }}
              >
                Sapling will log into Gradescope on your behalf to pull your
                grades. Your password is encrypted at rest with AES-GCM and is
                never shown again after this form.
              </p>
              <label
                className="mono"
                style={{
                  display: "block",
                  fontSize: 11,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-muted)",
                  marginBottom: 6,
                }}
              >
                Email
              </label>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                required
                autoComplete="username"
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  borderRadius: "var(--r-sm)",
                  border: "1px solid var(--border)",
                  background: "var(--bg-input)",
                  color: "var(--text)",
                  fontSize: 14,
                  marginBottom: 14,
                }}
              />
              <label
                className="mono"
                style={{
                  display: "block",
                  fontSize: 11,
                  letterSpacing: "0.12em",
                  textTransform: "uppercase",
                  color: "var(--text-muted)",
                  marginBottom: 6,
                }}
              >
                Password
              </label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
                autoComplete="current-password"
                style={{
                  width: "100%",
                  padding: "10px 12px",
                  borderRadius: "var(--r-sm)",
                  border: "1px solid var(--border)",
                  background: "var(--bg-input)",
                  color: "var(--text)",
                  fontSize: 14,
                  marginBottom: 20,
                }}
              />
              <div
                style={{
                  display: "flex",
                  gap: 10,
                  justifyContent: "space-between",
                  alignItems: "center",
                }}
              >
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={() => {
                    setError(null);
                    setStage("choose-mode");
                  }}
                  style={{ padding: "6px 10px", fontSize: 12 }}
                >
                  ← Back
                </button>
                <div style={{ display: "flex", gap: 10 }}>
                  <button type="button" className="btn" onClick={onClose}>
                    Cancel
                  </button>
                  <button type="submit" className="btn btn--primary">
                    Connect
                  </button>
                </div>
              </div>
            </form>
          )}

          {stage === "link" && (
            <div>
              <p
                style={{
                  fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
                  fontSize: 14,
                  lineHeight: 1.6,
                  color: "var(--text-dim)",
                  margin: "0 0 16px",
                }}
              >
                Which Gradescope course should map to{" "}
                <span style={{ color: "var(--text)", fontWeight: 500 }}>
                  {saplingCourseLabel}
                </span>
                ?
              </p>
              {courses.length === 0 ? (
                <p style={{ color: "var(--text-dim)", fontSize: 14 }}>
                  We didn&apos;t find any student courses on this Gradescope account.
                </p>
              ) : (
                <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {courses.map((c) => (
                    <li key={c.id} style={{ marginBottom: 6 }}>
                      <button
                        type="button"
                        onClick={() => onPickCourse(c.id)}
                        style={{
                          width: "100%",
                          textAlign: "left",
                          padding: "12px 14px",
                          border: "1px solid var(--border)",
                          borderRadius: "var(--r-sm)",
                          background: "var(--bg-panel)",
                          cursor: "pointer",
                          color: "var(--text)",
                          fontSize: 14,
                          display: "flex",
                          justifyContent: "space-between",
                          alignItems: "baseline",
                          gap: 12,
                          transition: "border-color var(--dur-fast) var(--ease)",
                        }}
                        onMouseEnter={(e) =>
                          (e.currentTarget.style.borderColor = "var(--border-strong)")
                        }
                        onMouseLeave={(e) =>
                          (e.currentTarget.style.borderColor = "var(--border)")
                        }
                      >
                        <span>
                          <span style={{ fontWeight: 500 }}>{c.name}</span>
                          {c.full_name && c.full_name !== c.name && (
                            <span style={{ color: "var(--text-dim)", marginLeft: 8 }}>
                              {c.full_name}
                            </span>
                          )}
                        </span>
                        <span
                          className="mono"
                          style={{ fontSize: 11, color: "var(--text-muted)" }}
                        >
                          {[c.semester, c.year].filter(Boolean).join(" ")}
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 20, gap: 10 }}>
                <button type="button" className="btn" onClick={onClose}>
                  Cancel
                </button>
                <button type="button" className="btn btn--ghost" onClick={onResetCredentials}>
                  Use different account
                </button>
              </div>
            </div>
          )}

          {stage === "connected" && (
            <div>
              <p
                style={{
                  fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
                  fontSize: 14,
                  lineHeight: 1.6,
                  color: "var(--text-dim)",
                  margin: "0 0 12px",
                }}
              >
                Your Gradescope account is connected. Go to any course in
                the gradebook to link it and sync grades.
              </p>
              {lastSyncedAt && (
                <p
                  className="mono"
                  style={{
                    fontSize: 11,
                    color: "var(--text-muted)",
                    letterSpacing: "-0.01em",
                    margin: "0 0 18px",
                  }}
                >
                  Last sync · {new Date(lastSyncedAt).toLocaleString()}
                </p>
              )}
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  gap: 12,
                  flexWrap: "wrap",
                }}
              >
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={onResetCredentials}
                >
                  Disconnect
                </button>
                <button type="button" className="btn btn--primary" onClick={onClose}>
                  Done
                </button>
              </div>
            </div>
          )}

          {(stage === "ready" || stage === "syncing") && (
            <div>
              <p
                style={{
                  fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
                  fontSize: 14,
                  lineHeight: 1.6,
                  color: "var(--text-dim)",
                  margin: "0 0 16px",
                }}
              >
                Sapling will pull every assignment from Gradescope course{" "}
                <span className="mono" style={{ color: "var(--text)" }}>
                  {linkedGsCourseId}
                </span>{" "}
                and update grades in {saplingCourseLabel}. New assignments
                land as Uncategorized. You can re-categorize them after.
              </p>
              {lastSyncedAt && (
                <p
                  className="mono"
                  style={{
                    fontSize: 11,
                    color: "var(--text-muted)",
                    letterSpacing: "-0.01em",
                    margin: "0 0 18px",
                  }}
                >
                  Last sync · {new Date(lastSyncedAt).toLocaleString()}
                </p>
              )}
              <div style={{ display: "flex", justifyContent: "space-between", gap: 12, flexWrap: "wrap" }}>
                <button
                  type="button"
                  className="btn btn--ghost"
                  onClick={onResetCredentials}
                  disabled={stage === "syncing"}
                >
                  Use different account
                </button>
                <div style={{ display: "flex", gap: 10 }}>
                  <button
                    type="button"
                    className="btn"
                    onClick={onClose}
                    disabled={stage === "syncing"}
                  >
                    Close
                  </button>
                  <button
                    type="button"
                    className="btn btn--primary"
                    onClick={onSyncNow}
                    disabled={stage === "syncing"}
                  >
                    {stage === "syncing" ? "Syncing…" : "Sync now"}
                  </button>
                </div>
              </div>
            </div>
          )}

          {stage === "done" && result && (
            <div>
              <p
                style={{
                  fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
                  fontSize: 15,
                  lineHeight: 1.6,
                  color: "var(--text)",
                  margin: "0 0 18px",
                }}
              >
                Pulled grades from Gradescope.
              </p>
              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "repeat(4, 1fr)",
                  gap: 12,
                  marginBottom: 24,
                }}
              >
                <SyncStat label="Added" value={result.inserted} />
                <SyncStat label="Updated" value={result.updated} />
                <SyncStat label="Skipped" value={result.skipped} muted />
                <SyncStat
                  label="Failed"
                  value={result.failed}
                  warn={result.failed > 0}
                />
              </div>
              <div style={{ display: "flex", justifyContent: "flex-end" }}>
                <button type="button" className="btn btn--primary" onClick={onClose}>
                  Done
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}

function SyncStat({
  label,
  value,
  muted,
  warn,
}: {
  label: string;
  value: number;
  muted?: boolean;
  warn?: boolean;
}) {
  return (
    <div>
      <div
        className="mono"
        style={{
          fontSize: 9,
          letterSpacing: "0.14em",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          marginBottom: 4,
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
          fontWeight: 500,
          fontSize: 28,
          color: warn ? "var(--err)" : muted ? "var(--text-dim)" : "var(--text)",
          letterSpacing: "-0.02em",
          lineHeight: 1.1,
        }}
      >
        {value}
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Mode picker — first step when a user has no saved Gradescope creds.
// Password mode covers accounts with a Gradescope-side password. Cookie
// mode is the only way to connect for SSO-only accounts (BU, etc.) since
// programmatic SSO with Duo 2FA isn't feasible.
// ───────────────────────────────────────────────────────────────────────────
function ChooseModeStep({
  onPickPassword,
  onPickCookies,
  onPickBuSso,
  onCancel,
}: {
  onPickPassword: () => void;
  onPickCookies: () => void;
  onPickBuSso: () => void;
  onCancel: () => void;
}) {
  return (
    <div>
      <p
        style={{
          fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
          fontSize: 14,
          lineHeight: 1.6,
          color: "var(--text-dim)",
          margin: "0 0 18px",
        }}
      >
        Three ways to connect. Pick whichever matches how you sign in to
        Gradescope.
      </p>

      <ModeCard
        title="BU SSO + Duo"
        body="If you sign in to Gradescope through BU. Enter your BU username and password here; tap Approve when your phone buzzes. Your BU password is used in-memory only. Sapling never writes it to disk. Only the resulting Gradescope session cookies are stored."
        onClick={onPickBuSso}
      />
      <div style={{ height: 12 }} />
      <ModeCard
        title="Email + password"
        body="If you set a Gradescope-side password (no SSO). We log in on your behalf each sync; password is encrypted at rest."
        onClick={onPickPassword}
      />
      <div style={{ height: 12 }} />
      <ModeCard
        title="Session cookies (manual)"
        body="If you'd rather paste session cookies yourself. Works for any school. Cookies last about two weeks before you have to re-paste."
        onClick={onPickCookies}
      />

      <div style={{ display: "flex", justifyContent: "flex-end", marginTop: 20 }}>
        <button type="button" className="btn" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// BU SSO username + password form. On submit, we move to the waiting
// stage and the backend runs the Playwright + Duo dance.
// ───────────────────────────────────────────────────────────────────────────
function BuSsoFormStep({
  username,
  password,
  setUsername,
  setPassword,
  onSubmit,
  onBack,
}: {
  username: string;
  password: string;
  setUsername: (v: string) => void;
  setPassword: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onBack: () => void;
}) {
  return (
    <form onSubmit={onSubmit}>
      <p
        style={{
          fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
          fontSize: 14,
          lineHeight: 1.6,
          color: "var(--text-dim)",
          margin: "0 0 18px",
        }}
      >
        Enter your BU login. Sapling drives a headless browser through{" "}
        <span className="mono" style={{ color: "var(--text)" }}>shib.bu.edu</span>{" "}
        on your behalf. Your password is held in memory for the request
        only, never written to disk. When you submit, your phone will
        buzz with a Duo push; tap{" "}
        <strong style={{ color: "var(--text)" }}>Approve</strong>.
      </p>

      <label
        className="mono"
        style={{
          display: "block",
          fontSize: 11,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          marginBottom: 6,
        }}
      >
        BU username
      </label>
      <input
        type="text"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        required
        autoComplete="username"
        placeholder="e.g. jackhe"
        style={{
          width: "100%",
          padding: "10px 12px",
          borderRadius: "var(--r-sm)",
          border: "1px solid var(--border)",
          background: "var(--bg-input)",
          color: "var(--text)",
          fontSize: 14,
          marginBottom: 14,
        }}
      />
      <label
        className="mono"
        style={{
          display: "block",
          fontSize: 11,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          marginBottom: 6,
        }}
      >
        BU password
      </label>
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        autoComplete="current-password"
        style={{
          width: "100%",
          padding: "10px 12px",
          borderRadius: "var(--r-sm)",
          border: "1px solid var(--border)",
          background: "var(--bg-input)",
          color: "var(--text)",
          fontSize: 14,
          marginBottom: 20,
        }}
      />

      <div
        style={{
          display: "flex",
          gap: 10,
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <button
          type="button"
          className="btn btn--ghost"
          onClick={onBack}
          style={{ padding: "6px 10px", fontSize: 12 }}
        >
          ← Back
        </button>
        <button type="submit" className="btn btn--primary">
          Sign in &amp; send Duo push
        </button>
      </div>
    </form>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Spinner + reassurance while Playwright drives BU WebLogin and the user
// taps Duo on their phone. The request stays open the whole time; no
// polling is needed.
// ───────────────────────────────────────────────────────────────────────────
function BuSsoWaitingStep() {
  const [elapsed, setElapsed] = React.useState(0);
  React.useEffect(() => {
    const t = setInterval(() => setElapsed((e) => e + 1), 1000);
    return () => clearInterval(t);
  }, []);
  return (
    <div style={{ paddingTop: 8 }}>
      <div style={{ display: "flex", gap: 14, alignItems: "center", marginBottom: 14 }}>
        <Spinner />
        <div>
          <div
            style={{
              fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
              fontWeight: 500,
              fontSize: 18,
              color: "var(--text)",
              letterSpacing: "-0.01em",
              marginBottom: 2,
            }}
          >
            Approve the Duo push on your phone.
          </div>
          <div
            className="mono"
            style={{
              fontSize: 11,
              color: "var(--text-muted)",
              letterSpacing: "-0.01em",
            }}
          >
            Waiting · {elapsed}s
          </div>
        </div>
      </div>
      <p
        style={{
          fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
          fontSize: 13,
          lineHeight: 1.6,
          color: "var(--text-dim)",
          margin: 0,
        }}
      >
        Sapling is signing in at shib.bu.edu now. The push usually arrives
        within a few seconds. We&apos;ll finish automatically once you tap
        Approve. Keep this window open.
      </p>
    </div>
  );
}

function Spinner() {
  return (
    <div
      aria-hidden="true"
      style={{
        width: 28,
        height: 28,
        borderRadius: "50%",
        border: "3px solid var(--border)",
        borderTopColor: "var(--accent)",
        animation: "gs-spin 0.9s linear infinite",
        flexShrink: 0,
      }}
    />
  );
}

function ModeCard({
  title,
  body,
  onClick,
}: {
  title: string;
  body: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      style={{
        width: "100%",
        textAlign: "left",
        padding: "14px 16px",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-md)",
        background: "var(--bg-panel)",
        cursor: "pointer",
        transition: "border-color var(--dur-fast) var(--ease), background-color var(--dur-fast) var(--ease)",
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.borderColor = "var(--border-strong)";
        e.currentTarget.style.background = "var(--bg-subtle)";
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.borderColor = "var(--border)";
        e.currentTarget.style.background = "var(--bg-panel)";
      }}
    >
      <div
        style={{
          fontFamily: "var(--font-display), 'Playfair Display', Georgia, serif",
          fontWeight: 500,
          fontSize: 17,
          color: "var(--text)",
          letterSpacing: "-0.01em",
          marginBottom: 4,
        }}
      >
        {title}
      </div>
      <div
        style={{
          fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
          fontSize: 13,
          lineHeight: 1.5,
          color: "var(--text-dim)",
        }}
      >
        {body}
      </div>
    </button>
  );
}

function CookiePasteStep({
  gradescopeSession,
  signedToken,
  setGradescopeSession,
  setSignedToken,
  onSubmit,
  onBack,
}: {
  gradescopeSession: string;
  signedToken: string;
  setGradescopeSession: (v: string) => void;
  setSignedToken: (v: string) => void;
  onSubmit: (e: React.FormEvent) => void;
  onBack: () => void;
}) {
  return (
    <form onSubmit={onSubmit}>
      <p
        style={{
          fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
          fontSize: 14,
          lineHeight: 1.6,
          color: "var(--text-dim)",
          margin: "0 0 12px",
        }}
      >
        Sign in to Gradescope normally in another tab (BU SSO + Duo,
        whatever your school uses). Then copy these two cookie values out
        of DevTools.
      </p>
      <ol
        style={{
          fontFamily: "var(--font-serif), 'Spectral', Georgia, serif",
          fontSize: 13,
          lineHeight: 1.6,
          color: "var(--text-dim)",
          margin: "0 0 18px",
          paddingLeft: 20,
        }}
      >
        <li>
          With Gradescope open, press <kbd style={kbd}>F12</kbd> (or right-click
          → Inspect).
        </li>
        <li>
          Go to <strong style={{ color: "var(--text)" }}>Application</strong> →{" "}
          <strong style={{ color: "var(--text)" }}>Cookies</strong> →{" "}
          <span className="mono" style={{ color: "var(--text)" }}>
            https://www.gradescope.com
          </span>
          .
        </li>
        <li>
          Copy the <strong style={{ color: "var(--text)" }}>Value</strong> of{" "}
          <span className="mono">_gradescope_session</span> and, if present,{" "}
          <span className="mono">signed_token</span>.
        </li>
      </ol>

      <label
        className="mono"
        style={{
          display: "block",
          fontSize: 11,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          marginBottom: 6,
        }}
      >
        _gradescope_session <span style={{ color: "var(--err)" }}>*</span>
      </label>
      <textarea
        value={gradescopeSession}
        onChange={(e) => setGradescopeSession(e.target.value)}
        required
        rows={2}
        spellCheck={false}
        autoComplete="off"
        style={{
          width: "100%",
          padding: "10px 12px",
          borderRadius: "var(--r-sm)",
          border: "1px solid var(--border)",
          background: "var(--bg-input)",
          color: "var(--text)",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          resize: "vertical",
          marginBottom: 14,
        }}
      />

      <label
        className="mono"
        style={{
          display: "block",
          fontSize: 11,
          letterSpacing: "0.12em",
          textTransform: "uppercase",
          color: "var(--text-muted)",
          marginBottom: 6,
        }}
      >
        signed_token <span style={{ color: "var(--text-muted)" }}>(optional)</span>
      </label>
      <textarea
        value={signedToken}
        onChange={(e) => setSignedToken(e.target.value)}
        rows={2}
        spellCheck={false}
        autoComplete="off"
        style={{
          width: "100%",
          padding: "10px 12px",
          borderRadius: "var(--r-sm)",
          border: "1px solid var(--border)",
          background: "var(--bg-input)",
          color: "var(--text)",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          resize: "vertical",
          marginBottom: 20,
        }}
      />

      <div
        style={{
          display: "flex",
          gap: 10,
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <button
          type="button"
          className="btn btn--ghost"
          onClick={onBack}
          style={{ padding: "6px 10px", fontSize: 12 }}
        >
          ← Back
        </button>
        <button type="submit" className="btn btn--primary">
          Verify &amp; connect
        </button>
      </div>
    </form>
  );
}

const kbd: React.CSSProperties = {
  display: "inline-block",
  padding: "1px 6px",
  border: "1px solid var(--border)",
  borderBottomWidth: 2,
  borderRadius: 4,
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  background: "var(--bg-subtle)",
  color: "var(--text)",
};
