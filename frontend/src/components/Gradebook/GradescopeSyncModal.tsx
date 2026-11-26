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
import { extractErrorDetail, humanizeError, statusOf } from "@/lib/errorMessage";
import { useScrollLock } from "@/lib/useScrollLock";
import {
  GRADESCOPE_AUTH_FAILED,
  gradescopeConnectionState,
  gradescopeErrorCode,
  gradescopeReauthMessage,
  needsGradescopeSignIn,
} from "./gradescopeState";
import {
  canDismissGradescopeDialog,
  connectedCopy,
  gradescopeDialogTitle,
  type Stage,
} from "./gradescopeDialog";

interface Props {
  open: boolean;
  userId: string;
  /** Course id to link + sync. Omit for the settings-page "manage connection
   *  only" flow — the modal will skip link/sync and stop at "connected". */
  saplingCourseId?: string;
  /** Pretty label shown in the kicker. Defaults to "Gradescope" when no
   *  course is provided (settings mode). */
  saplingCourseLabel?: string;
  semester?: string;
  reconnect?: boolean;
  onClose: () => void;
  /** Fired after a successful sync. Not called in settings/connect-only mode. */
  onSynced?: () => void;
}

/**
 * Copy for a failed BU SSO attempt. Classified on the status and the RAW
 * server detail: humanizeError drops the status and swaps any long or
 * diagnostic detail (the backend appends a page dump) for generic copy, which
 * turned a Duo timeout into "That took too long" and a BU failure into
 * "Your session expired" — Sapling's session was never the problem here.
 */
function buSsoErrorCopy(e: unknown): string {
  const { detail = "", status } = extractErrorDetail(e);
  // Match the backend's sentence, never the page dump appended after it.
  const head = detail.split(/\bpage=/)[0];
  if (status === 408 || /duo.*time.?out|wasn.?t approved/i.test(head)) {
    return "Duo push wasn't approved in time. Tap Approve quickly when your phone buzzes.";
  }
  if (/login failed|incorrect|invalid/i.test(head)) {
    return "BU login failed. Username or password is incorrect.";
  }
  if (/denied|declined|rejected/i.test(head)) {
    return "Duo push was denied. Try again and tap Approve.";
  }
  if (/captcha/i.test(head)) {
    return "BU asked for a CAPTCHA. The automated flow can't solve those. Use the cookie-paste option instead.";
  }
  if (gradescopeErrorCode(e) === GRADESCOPE_AUTH_FAILED) {
    // Status-less so a diagnostic detail falls back to BU copy, not the
    // generic status copy. (A 401 is Sapling's own session, never this.)
    return humanizeError({ detail }, "BU sign-in failed. Try again, or connect with session cookies instead.");
  }
  return humanizeError(e, "SSO failed unexpectedly.");
}

export function GradescopeSyncModal(props: Props) {
  if (!props.open) return null;
  // Keep requests and credential drafts scoped to one account/course/term
  // and one opening. An older request may finish after navigation or close,
  // but it must never populate the next dialog with that previous context.
  return <GradescopeSyncDialog key={JSON.stringify([
    props.userId, props.saplingCourseId, props.semester, props.reconnect,
  ])} {...props} />;
}

/** Keyboard focus trap: Tab / Shift+Tab wrap around the dialog's enabled
 *  controls, and a dialog with none keeps focus on itself. */
function trapDialogTab(event: React.KeyboardEvent<HTMLDivElement>) {
  const controls = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(
    'button:not(:disabled), input:not(:disabled), textarea:not(:disabled), select:not(:disabled), a[href]',
  ));
  const first = controls[0];
  const last = controls.at(-1);
  if (!first) {
    event.preventDefault();
    event.currentTarget.focus();
  } else if (event.shiftKey && (document.activeElement === first || document.activeElement === event.currentTarget)) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first.focus();
  }
}

/**
 * The dialog's state machine: every piece of state, the stage loaders and the
 * submit/link/sync/reset handlers, in the order the dialog has always run them.
 */
function useGradescopeSyncFlow({
  userId,
  saplingCourseId,
  semester,
  reconnect = false,
  onSynced,
}: Omit<Props, "open" | "onClose" | "saplingCourseLabel">) {
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
  // A queued sync (#116) that outlasted the server's wait: it keeps running
  // and the dialog polls for its outcome. It may be closed meanwhile; the
  // poll carries on and still refreshes the gradebook when the sync ends.
  const [syncPending, setSyncPending] = React.useState(false);
  const [saving, setSaving] = React.useState(false);
  const submitting = React.useRef(false);
  const active = React.useRef(true);
  const dialogRef = React.useRef<HTMLDivElement>(null);
  const fieldId = React.useId();
  useScrollLock(true);

  React.useEffect(() => {
    active.current = true;
    return () => { active.current = false; };
  }, []);

  React.useEffect(() => setMounted(true), []);

  React.useEffect(() => {
    if (!mounted) return;
    const previousFocus = document.activeElement;
    dialogRef.current?.focus();
    return () => {
      if (previousFocus instanceof HTMLElement && previousFocus.isConnected) previousFocus.focus();
    };
  }, [mounted]);

  React.useEffect(() => {
    if (mounted && !dialogRef.current?.contains(document.activeElement)) dialogRef.current?.focus();
  }, [mounted, stage]);

  // Run token for the stage loaders (#770). refreshState runs from the open
  // effect AND from handlers (after a credential save, "Retry connection");
  // chooseCourse from refreshState and from "Change course" / an ambiguous
  // sync. Each start supersedes whatever loader was in flight, so a slower,
  // older answer can never move the dialog off the stage a newer one chose.
  const runRef = React.useRef(0);
  const beginRun = React.useCallback(() => ++runRef.current, []);
  const isLatest = React.useCallback(
    (run: number) => active.current && run === runRef.current,
    [],
  );

  const failVerification = React.useCallback((run: number, e: unknown) => {
    if (!isLatest(run)) return;
    setError(humanizeError(e, "Couldn't verify the Gradescope connection."));
    // Only a typed Gradescope rejection means "sign in to Gradescope again".
    // A 401 is Sapling's own session and is left to the app's session handling.
    setStage(needsGradescopeSignIn(e) ? "choose-mode" : "verification-error");
  }, [isLatest]);

  // Listing courses is a full live Gradescope login + scrape (rate-limited
  // server-side), so it only runs when the user actually has to pick one.
  // It doubles as the check that saved credentials still authenticate.
  const chooseCourse = React.useCallback(async () => {
    const run = beginRun();
    setStage("loading");
    try {
      const gs = await listGradescopeCourses(userId);
      if (!isLatest(run)) return;
      setCourses(gs.courses);
      setStage("link");
    } catch (e: unknown) {
      failVerification(run, e);
    }
  }, [userId, beginRun, isLatest, failVerification]);

  const refreshState = React.useCallback(async () => {
    const run = beginRun();
    setError(null);
    setStage("loading");
    try {
      const status = await getGradescopeStatus(userId);
      if (!isLatest(run)) return;
      setLastSyncedAt(status.last_synced_at);
      const state = gradescopeConnectionState(status);
      if (state === "disconnected") {
        // No saved creds — let the user pick how they want to connect.
        setStage("choose-mode");
        return;
      }
      if (state === "needs_reauth") {
        // Gradescope already rejected the saved sign-in; a sync would only
        // fail the same way, so go straight to reconnecting.
        setError(gradescopeReauthMessage(status));
        setStage("choose-mode");
        return;
      }
      // Settings-mode (no course): there's no sync to prove the saved
      // credentials still work, so verify them here with one live listing.
      if (!saplingCourseId) {
        const gs = await listGradescopeCourses(userId);
        if (!isLatest(run)) return;
        setCourses(gs.courses);
        setStage("connected");
        return;
      }
      const links = await listGradescopeLinks(userId, semester);
      if (!isLatest(run)) return;
      const myLink = links.links.find((l) => l.sapling_course_id === saplingCourseId);
      setLastSyncedAt(myLink?.last_synced_at ?? null);
      if (!myLink) {
        await chooseCourse();
        return;
      }
      // Already linked: show "ready" without logging in. Sync logs in itself,
      // and an expired session there returns to sign-in (onSyncNow).
      setLinkedGsCourseId(myLink.gradescope_course_id);
      setStage("ready");
    } catch (e: unknown) {
      failVerification(run, e);
    }
  }, [userId, saplingCourseId, semester, chooseCourse, beginRun, isLatest, failVerification]);

  React.useEffect(() => {
    setResult(null);
    setError(null);
    setEmail("");
    setPassword("");
    setGradescopeSession("");
    setSignedToken("");
    setBuUsername("");
    setBuPassword("");
    if (reconnect) setStage("choose-mode");
    else refreshState();
  }, [reconnect, refreshState]);

  /** Move to another stage with the previous stage's error cleared. */
  function goTo(next: Stage) {
    setError(null);
    setStage(next);
  }

  async function onSubmitCredentials(e: React.FormEvent) {
    e.preventDefault();
    if (submitting.current) return;
    submitting.current = true;
    setSaving(true);
    setError(null);
    try {
      await saveGradescopeCredentials(userId, {
        auth_mode: "password",
        email: email.trim(),
        password,
      });
      if (!active.current) return;
      setPassword("");
      await refreshState();
    } catch (e: unknown) {
      const msg = humanizeError(e, "Couldn't connect to Gradescope.");
      setError(msg.includes("Invalid") ? "Invalid Gradescope credentials." : msg);
    } finally {
      submitting.current = false;
      setSaving(false);
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
    if (submitting.current) return;
    submitting.current = true;
    // Move to "waiting for Duo" stage immediately so the user knows
    // their phone is about to buzz. The fetch promise stays open for up
    // to ~125s while Playwright drives the SSO + Duo flow on the server.
    setStage("bu-sso-waiting");
    try {
      await connectGradescopeViaBuSso(userId, username, buPassword, 120);
      if (!active.current) return;
      // Clear the password from memory as soon as we don't need it.
      setBuPassword("");
      setBuUsername("");
      await refreshState();
    } catch (e: unknown) {
      if (!active.current) return;
      setBuPassword(""); // never leave a wrong password sitting in state
      setError(buSsoErrorCopy(e));
      setStage("bu-sso-form");
    } finally {
      submitting.current = false;
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
    if (submitting.current) return;
    submitting.current = true;
    setSaving(true);
    try {
      await saveGradescopeCredentials(userId, {
        auth_mode: "cookies",
        gradescope_session: session,
        signed_token: signedToken.trim() || undefined,
      });
      if (!active.current) return;
      setGradescopeSession("");
      setSignedToken("");
      await refreshState();
    } catch (e: unknown) {
      // Show what the backend actually said. The previous canned message fired
      // on any "expired"/"invalid" substring, which swallowed the specific
      // reason — expired session vs. truncated cookie vs. a 401 from Sapling's
      // own require_self — and pointed all three at "re-copy your cookies",
      // advice that is wrong for two of them. humanizeError pulls `detail` off
      // the ApiError envelope and still guarantees no raw JSON reaches the UI.
      setError(
        humanizeError(
          e,
          "Those cookies didn't authenticate. Copy them again from a freshly signed-in tab.",
        ),
      );
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  async function onPickCourse(gsCourseId: string) {
    if (!saplingCourseId || submitting.current) return;
    submitting.current = true;
    setSaving(true);
    setError(null);
    try {
      await linkGradescopeCourse(userId, saplingCourseId, gsCourseId, semester);
      if (!active.current) return;
      setLinkedGsCourseId(gsCourseId);
      setLastSyncedAt(null);
      setStage("ready");
    } catch (e: unknown) {
      setError(humanizeError(e, "Couldn't link course"));
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  async function onSyncNow() {
    if (!saplingCourseId || submitting.current) return;
    submitting.current = true;
    setError(null);
    setSyncPending(false);
    setStage("syncing");
    let wentPending = false;
    try {
      const res = await syncGradescopeCourse(userId, saplingCourseId, semester, {
        onPending: () => {
          wentPending = true;
          if (active.current) setSyncPending(true);
        },
      });
      if (!active.current) {
        // Closed while a queued sync was still running (the pending note
        // allows that): it has finished now, so refresh the gradebook as the
        // note promised. A sync that never went pending reports nothing.
        if (wentPending) onSynced?.();
        return;
      }
      setResult(res);
      setStage("done");
      onSynced?.();
    } catch (e: unknown) {
      if (!active.current) return;
      setError(humanizeError(e, "Sync failed"));
      const status = statusOf(e);
      // The typed Gradescope rejection, never a bare 401 (Sapling's session).
      if (needsGradescopeSignIn(e)) setStage("choose-mode");
      // More than one link matches: re-picking replaces them with one, so a
      // retry can't hit the same ambiguity again.
      else if (status === 409) void chooseCourse();
      else setStage("ready");
    } finally {
      submitting.current = false;
      if (active.current) setSyncPending(false);
    }
  }

  async function onResetCredentials() {
    // Never while a save, link or sync is in flight: deleting the credentials
    // under a running sync would leave it to report into the sign-in screen.
    if (submitting.current) return;
    if (!window.confirm("Remove your Gradescope credentials? You'll need to re-enter them to sync again.")) return;
    if (submitting.current) return;
    submitting.current = true;
    setSaving(true);
    // Supersede any loader still in flight so it can't move the dialog off
    // the sign-in choices once the credentials are gone.
    const run = beginRun();
    try {
      await deleteGradescopeCredentials(userId);
      if (!isLatest(run)) return;
      setLinkedGsCourseId(null);
      setError(null);
      setStage("choose-mode");
    } catch (e: unknown) {
      if (!isLatest(run)) return;
      setError(humanizeError(e, "Couldn't remove credentials"));
    } finally {
      submitting.current = false;
      setSaving(false);
    }
  }

  return {
    mounted, stage, error, lastSyncedAt,
    email, setEmail, password, setPassword,
    gradescopeSession, setGradescopeSession, signedToken, setSignedToken,
    buUsername, setBuUsername, buPassword, setBuPassword,
    courses, linkedGsCourseId, result, syncPending, saving,
    dialogRef, fieldId,
    goTo, refreshState, chooseCourse,
    onSubmitCredentials, onSubmitBuSso, onSubmitCookies,
    onPickCourse, onSyncNow, onResetCredentials,
  };
}

type SyncFlow = ReturnType<typeof useGradescopeSyncFlow>;

// The wrapper only mounts this while open, so `open` itself is never read here.
function GradescopeSyncDialog({
  saplingCourseLabel,
  onClose,
  ...flowProps
}: Omit<Props, "open">) {
  const flow = useGradescopeSyncFlow(flowProps);
  const { stage, error, result, syncPending, saving, dialogRef } = flow;

  if (!flow.mounted) return null;

  function dismiss() {
    if (canDismissGradescopeDialog(stage, saving, syncPending)) onClose();
  }

  return createPortal(
    <div
      ref={dialogRef}
      tabIndex={-1}
      role="dialog"
      aria-modal="true"
      aria-labelledby="gs-modal-title"
      className="fixed inset-0 bg-[rgba(15,_17,_16,_0.55)] flex items-center justify-center z-100 p-4"
      onClick={dismiss}
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          dismiss();
        }
        if (event.key !== "Tab") return;
        trapDialogTab(event);
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="bg-bg-panel rounded-lg py-7 px-8 w-[min(560px,_100%)] max-h-[min(640px,_90vh)] flex flex-col shadow-lg"
      >
        <header className="mb-4.5">
          <div
            className="mono text-sm text-text-muted mb-2"
          >
            Gradescope · {saplingCourseLabel || "Connection"}
          </div>
          <h2
            id="gs-modal-title"
            className="font-display font-medium text-[24px] tracking-[-0.01em] text-text m-0"
          >
            {gradescopeDialogTitle(stage, result)}
          </h2>
        </header>

        {error && (
          <div
            role="alert"
            className="py-2.5 px-3 rounded-sm bg-err-soft text-err text-md mb-3.5 border border-[color-mix(in_oklab,_var(--err)_25%,_transparent)]"
          >
            {error}
          </div>
        )}

        {renderStageBody(flow, saplingCourseLabel, onClose)}
      </div>
    </div>,
    document.body,
  );
}

/**
 * The scrolling stage area. A plain function (not a component) so the tree is
 * exactly the one the dialog always rendered: one slot per stage, in the same
 * order, so each stage mounts and unmounts its own subtree as before.
 */
function renderStageBody(flow: SyncFlow, saplingCourseLabel: string | undefined, onClose: () => void) {
  const { stage, saving, result } = flow;
  const backToChoices = () => flow.goTo("choose-mode");
  return (
    <div className="flex-1 overflow-y-auto min-h-0">
      {stage === "loading" && (
        <p className="text-text-dim text-base">Loading…</p>
      )}

      {stage === "verification-error" && (
        <VerificationErrorStep
          onRetry={() => void flow.refreshState()}
          onReconnect={backToChoices}
          onCancel={onClose}
        />
      )}

      {stage === "choose-mode" && (
        <ChooseModeStep
          onPickPassword={() => flow.goTo("credentials")}
          onPickCookies={() => flow.goTo("cookies")}
          onPickBuSso={() => flow.goTo("bu-sso-form")}
          onCancel={onClose}
        />
      )}

      {stage === "bu-sso-form" && (
        <BuSsoFormStep
          username={flow.buUsername}
          password={flow.buPassword}
          setUsername={flow.setBuUsername}
          setPassword={flow.setBuPassword}
          onSubmit={flow.onSubmitBuSso}
          onBack={backToChoices}
        />
      )}

      {stage === "bu-sso-waiting" && <BuSsoWaitingStep />}

      {stage === "cookies" && (
        <CookiePasteStep
          gradescopeSession={flow.gradescopeSession}
          signedToken={flow.signedToken}
          setGradescopeSession={flow.setGradescopeSession}
          setSignedToken={flow.setSignedToken}
          saving={saving}
          onSubmit={flow.onSubmitCookies}
          onBack={backToChoices}
        />
      )}

      {stage === "credentials" && (
        <CredentialsStep flow={flow} onBack={backToChoices} onCancel={onClose} />
      )}

      {stage === "link" && (
        <LinkStep
          saplingCourseLabel={saplingCourseLabel}
          courses={flow.courses}
          saving={saving}
          onPick={flow.onPickCourse}
          onCancel={onClose}
          onReset={flow.onResetCredentials}
        />
      )}

      {stage === "connected" && (
        <ConnectedStep
          courseCount={flow.courses.length}
          lastSyncedAt={flow.lastSyncedAt}
          saving={saving}
          onReset={flow.onResetCredentials}
          onDone={onClose}
        />
      )}

      {(stage === "ready" || stage === "syncing") && (
        <ReadyStep
          syncing={stage === "syncing"}
          flow={flow}
          saplingCourseLabel={saplingCourseLabel}
          onClose={onClose}
        />
      )}

      {stage === "done" && result && (
        <DoneStep result={result} onRetry={flow.onSyncNow} onDone={onClose} />
      )}
    </div>
  );
}

function VerificationErrorStep({
  onRetry,
  onReconnect,
  onCancel,
}: {
  onRetry: () => void;
  onReconnect: () => void;
  onCancel: () => void;
}) {
  return (
    <div>
      <p className="text-text-dim">
        Your saved credentials have not been changed. Retry the connection check,
        or reconnect if you want to use a different Gradescope session.
      </p>
      <div className="flex flex-wrap gap-2.5">
        <button type="button" className="btn btn--primary" onClick={onRetry}>
          Retry connection
        </button>
        <button type="button" className="btn" onClick={onReconnect}>
          Reconnect
        </button>
        <button type="button" className="btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}

function CredentialsStep({
  flow,
  onBack,
  onCancel,
}: {
  flow: SyncFlow;
  onBack: () => void;
  onCancel: () => void;
}) {
  const { fieldId, saving } = flow;
  return (
    <form onSubmit={flow.onSubmitCredentials}>
      <p
        className="font-serif text-base leading-[1.6] text-text-dim mt-0 mx-0 mb-4.5"
      >
        Sapling uses your password once, to sign in to Gradescope, and
        keeps only the session that sign-in creates, never the password.
        When that session expires, you&apos;ll enter your password again.
      </p>
      <label
        htmlFor={`${fieldId}-email`}
        className="mono block text-md text-text-muted mb-1.5"
      >
        Email
      </label>
      <input
        id={`${fieldId}-email`}
        type="email"
        value={flow.email}
        onChange={(e) => flow.setEmail(e.target.value)}
        required
        autoComplete="username"
        className="w-full py-2.5 px-3 rounded-sm border border-border bg-bg-input text-text text-base mb-3.5"
      />
      <label
        htmlFor={`${fieldId}-password`}
        className="mono block text-md text-text-muted mb-1.5"
      >
        Password
      </label>
      <input
        id={`${fieldId}-password`}
        type="password"
        value={flow.password}
        onChange={(e) => flow.setPassword(e.target.value)}
        required
        autoComplete="current-password"
        className="w-full py-2.5 px-3 rounded-sm border border-border bg-bg-input text-text text-base mb-5"
      />
      <div
        className="flex gap-2.5 justify-between items-center"
      >
        <button
          type="button"
          className="btn btn--ghost py-1.5 px-2.5 text-sm"
          disabled={saving}
          onClick={onBack}
        >
          ← Back
        </button>
        <div className="flex gap-2.5">
          <button type="button" className="btn" onClick={onCancel} disabled={saving}>
            Cancel
          </button>
          <button type="submit" className="btn btn--primary" disabled={saving}>
            {saving ? "Connecting…" : "Connect"}
          </button>
        </div>
      </div>
    </form>
  );
}

function LinkStep({
  saplingCourseLabel,
  courses,
  saving,
  onPick,
  onCancel,
  onReset,
}: {
  saplingCourseLabel: string | undefined;
  courses: GradescopeCourse[];
  saving: boolean;
  onPick: (gsCourseId: string) => void;
  onCancel: () => void;
  onReset: () => void;
}) {
  return (
    <div>
      <p
        className="font-serif text-base leading-[1.6] text-text-dim mt-0 mx-0 mb-4"
      >
        Which Gradescope course should map to{" "}
        <span className="text-text font-medium">
          {saplingCourseLabel}
        </span>
        ?
      </p>
      {courses.length === 0 ? (
        <p className="text-text-dim text-base">
          We didn&apos;t find any student courses on this Gradescope account.
        </p>
      ) : (
        <ul className="list-none p-0 m-0">
          {courses.map((c) => (
            <li key={c.id} className="mb-1.5">
              <button
                type="button"
                disabled={saving}
                onClick={() => onPick(c.id)}
                className="w-full text-left py-3 px-3.5 border border-border rounded-sm bg-bg-panel cursor-pointer text-text text-base flex justify-between items-baseline gap-3 [transition:border-color_var(--dur-fast)_var(--ease)]"
                onMouseEnter={(e) =>
                  (e.currentTarget.style.borderColor = "var(--border-strong)")
                }
                onMouseLeave={(e) =>
                  (e.currentTarget.style.borderColor = "var(--border)")
                }
              >
                <span>
                  <span className="font-medium">{c.name}</span>
                  {c.full_name && c.full_name !== c.name && (
                    <span className="text-text-dim ml-2">
                      {c.full_name}
                    </span>
                  )}
                </span>
                <span
                  className="mono text-xs text-text-muted"
                >
                  {[c.semester, c.year].filter(Boolean).join(" ")}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="flex justify-end mt-5 gap-2.5">
        <button type="button" className="btn" onClick={onCancel} disabled={saving}>
          Cancel
        </button>
        <button type="button" className="btn btn--ghost" onClick={onReset} disabled={saving}>
          Use different account
        </button>
      </div>
    </div>
  );
}

function ConnectedStep({
  courseCount,
  lastSyncedAt,
  saving,
  onReset,
  onDone,
}: {
  courseCount: number;
  lastSyncedAt: string | null;
  saving: boolean;
  onReset: () => void;
  onDone: () => void;
}) {
  return (
    <div>
      <p
        className="font-serif text-base leading-[1.6] text-text-dim mt-0 mx-0 mb-3"
      >
        {connectedCopy(courseCount)}
      </p>
      {lastSyncedAt && (
        <p
          className="mono text-xs text-text-muted tracking-[-0.01em] mt-0 mx-0 mb-4.5"
        >
          Last sync · {new Date(lastSyncedAt).toLocaleString()}
        </p>
      )}
      <div
        className="flex justify-between gap-3 flex-wrap"
      >
        <button
          type="button"
          className="btn btn--ghost"
          onClick={onReset}
          disabled={saving}
        >
          Disconnect
        </button>
        <button type="button" className="btn btn--primary" onClick={onDone} disabled={saving}>
          Done
        </button>
      </div>
    </div>
  );
}

/** Both "ready" and "syncing": one component at one slot, so starting a sync
 *  updates this subtree in place instead of remounting it. */
function ReadyStep({
  syncing,
  flow,
  saplingCourseLabel,
  onClose,
}: {
  syncing: boolean;
  flow: SyncFlow;
  saplingCourseLabel: string | undefined;
  onClose: () => void;
}) {
  const { lastSyncedAt, syncPending, saving } = flow;
  return (
    <div>
      <p
        className="font-serif text-base leading-[1.6] text-text-dim mt-0 mx-0 mb-4"
      >
        Sapling will pull every assignment from Gradescope course{" "}
        <span className="mono text-text">
          {flow.linkedGsCourseId}
        </span>{" "}
        and update grades in {saplingCourseLabel}. New assignments
        are matched to categories by title where possible. You can re-categorize them after.
      </p>
      {lastSyncedAt && (
        <p
          className="mono text-xs text-text-muted tracking-[-0.01em] mt-0 mx-0 mb-4.5"
        >
          Last sync · {new Date(lastSyncedAt).toLocaleString()}
        </p>
      )}
      {syncing && syncPending && (
        <p
          role="status"
          className="text-md leading-[1.5] text-text-dim mt-0 mx-0 mb-4"
        >
          Still syncing — this one is taking longer than usual. We&apos;ll refresh
          your gradebook when it finishes.
        </p>
      )}
      <div className="flex justify-between gap-3 flex-wrap">
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => void flow.chooseCourse()}
          disabled={syncing || saving}
        >
          Change course
        </button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={flow.onResetCredentials}
          disabled={syncing || saving}
        >
          Use different account
        </button>
        <div className="flex gap-2.5">
          <button
            type="button"
            className="btn"
            onClick={onClose}
            disabled={(syncing && !syncPending) || saving}
          >
            Close
          </button>
          <button
            type="button"
            className="btn btn--primary"
            onClick={flow.onSyncNow}
            disabled={syncing || saving}
          >
            {syncing ? "Syncing…" : "Sync now"}
          </button>
        </div>
      </div>
    </div>
  );
}

function DoneStep({
  result,
  onRetry,
  onDone,
}: {
  result: GradescopeSyncResult;
  onRetry: () => void;
  onDone: () => void;
}) {
  return (
    <div>
      <p
        className="font-serif text-[15px] leading-[1.6] text-text mt-0 mx-0 mb-4.5"
      >
        {result.failed > 0
          ? "Some assignments could not be saved. Retry the sync to import the remaining grades."
          : "Pulled grades from Gradescope."}
      </p>
      <div
        className="grid grid-cols-[repeat(4,_1fr)] gap-3 mb-6"
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
      <div className="flex gap-2.5 justify-end">
        {result.failed > 0 && (
          <button type="button" className="btn btn--primary" onClick={onRetry}>
            Retry sync
          </button>
        )}
        <button type="button" className="btn btn--primary" onClick={onDone}>
          Done
        </button>
      </div>
    </div>
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
        className="mono text-xs text-text-muted mb-1"
      >
        {label}
      </div>
      <div
        className="font-display font-medium text-[28px] tracking-[-0.02em] leading-[1.1]" style={{ color: warn ? "var(--err)" : muted ? "var(--text-dim)" : "var(--text)" }}
      >
        {value}
      </div>
    </div>
  );
}

// ───────────────────────────────────────────────────────────────────────────
// Mode picker — first step when a user has no saved Gradescope creds.
// Password mode covers accounts with a Gradescope-side password. Cookie
// mode also supports schools without an automated SSO flow.
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
        className="font-serif text-base leading-[1.6] text-text-dim mt-0 mx-0 mb-4.5"
      >
        Three ways to connect. Pick whichever matches how you sign in to
        Gradescope.
      </p>

      <ModeCard
        title="BU SSO + Duo"
        body="If you sign in to Gradescope through BU. Enter your BU username and password here; tap Approve when your phone buzzes. Your BU password is used in-memory only. Sapling never writes it to disk. Only the resulting Gradescope session cookies are stored."
        onClick={onPickBuSso}
      />
      <div className="h-3" />
      <ModeCard
        title="Email + password"
        body="If you set a Gradescope-side password (no SSO). We sign in once and keep only the Gradescope session, never your password; enter it again when the session expires."
        onClick={onPickPassword}
      />
      <div className="h-3" />
      <ModeCard
        title="Session cookies (manual)"
        body="If you'd rather paste session cookies yourself. Works for any school. Reconnect when the session expires or you sign out of Gradescope."
        onClick={onPickCookies}
      />

      <div className="flex justify-end mt-5">
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
  const fieldId = React.useId();
  return (
    <form onSubmit={onSubmit}>
      <p
        className="font-serif text-base leading-[1.6] text-text-dim mt-0 mx-0 mb-4.5"
      >
        Enter your BU login. Sapling drives a headless browser through{" "}
        <span className="mono text-text">shib.bu.edu</span>{" "}
        on your behalf. Your password is held in memory for the request
        only, never written to disk. When you submit, your phone will
        buzz with a Duo push; tap{" "}
        <strong className="text-text">Approve</strong>.
      </p>

      <label
        htmlFor={`${fieldId}-username`}
        className="mono block text-md text-text-muted mb-1.5"
      >
        BU username
      </label>
      <input
        id={`${fieldId}-username`}
        type="text"
        value={username}
        onChange={(e) => setUsername(e.target.value)}
        required
        autoComplete="username"
        placeholder="e.g. jackhe"
        className="w-full py-2.5 px-3 rounded-sm border border-border bg-bg-input text-text text-base mb-3.5"
      />
      <label
        htmlFor={`${fieldId}-password`}
        className="mono block text-md text-text-muted mb-1.5"
      >
        BU password
      </label>
      <input
        id={`${fieldId}-password`}
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
        required
        autoComplete="current-password"
        className="w-full py-2.5 px-3 rounded-sm border border-border bg-bg-input text-text text-base mb-5"
      />

      <div
        className="flex gap-2.5 justify-between items-center"
      >
        <button
          type="button"
          className="btn btn--ghost py-1.5 px-2.5 text-sm"
          onClick={onBack}
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
    <div className="pt-2">
      <div className="flex gap-3.5 items-center mb-3.5">
        <Spinner />
        <div>
          <div
            className="font-display font-medium text-xl text-text tracking-[-0.01em] mb-0.5"
          >
            Approve the Duo push on your phone.
          </div>
          <div
            className="mono text-xs text-text-muted tracking-[-0.01em]"
          >
            Waiting · {elapsed}s
          </div>
        </div>
      </div>
      <p
        className="font-serif text-md leading-[1.6] text-text-dim m-0"
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
      className="w-7 h-7 rounded-[50%] border-3 border-border border-t-accent [animation:gs-spin_0.9s_linear_infinite] shrink-0"
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
      className="w-full text-left py-3.5 px-4 border border-border rounded-md bg-bg-panel cursor-pointer [transition:border-color_var(--dur-fast)_var(--ease),_background-color_var(--dur-fast)_var(--ease)]"
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
        className="font-display font-medium text-[17px] text-text tracking-[-0.01em] mb-1"
      >
        {title}
      </div>
      <div
        className="font-serif text-md leading-[1.5] text-text-dim"
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
  saving,
  onSubmit,
  onBack,
}: {
  gradescopeSession: string;
  signedToken: string;
  setGradescopeSession: (v: string) => void;
  setSignedToken: (v: string) => void;
  saving: boolean;
  onSubmit: (e: React.FormEvent) => void;
  onBack: () => void;
}) {
  const fieldId = React.useId();
  return (
    <form onSubmit={onSubmit}>
      <p
        className="font-serif text-base leading-[1.6] text-text-dim mt-0 mx-0 mb-3"
      >
        Sign in to Gradescope normally in another tab (BU SSO + Duo,
        whatever your school uses). Then copy these two cookie values out
        of DevTools.
      </p>
      <ol
        className="font-serif text-md leading-[1.6] text-text-dim mt-0 mx-0 mb-4.5 pl-5"
      >
        <li>
          With Gradescope open, press <kbd className="inline-block py-px px-1.5 border border-border [border-bottom-width:2px] rounded-xs font-sans text-xs bg-bg-subtle text-text">F12</kbd> (or right-click
          → Inspect).
        </li>
        <li>
          Go to <strong className="text-text">Application</strong> →{" "}
          <strong className="text-text">Cookies</strong> →{" "}
          <span className="mono text-text">
            https://www.gradescope.com
          </span>
          .
        </li>
        <li>
          Copy the <strong className="text-text">Value</strong> of{" "}
          <span className="mono">_gradescope_session</span> and, if present,{" "}
          <span className="mono">signed_token</span>.
        </li>
      </ol>

      <label
        htmlFor={`${fieldId}-session`}
        className="mono block text-md text-text-muted mb-1.5"
      >
        _gradescope_session <span className="text-err">*</span>
      </label>
      <textarea
        id={`${fieldId}-session`}
        value={gradescopeSession}
        onChange={(e) => setGradescopeSession(e.target.value)}
        required
        rows={2}
        spellCheck={false}
        autoComplete="off"
        className="w-full py-2.5 px-3 rounded-sm border border-border bg-bg-input text-text font-code text-sm resize-y mb-3.5"
      />

      <label
        htmlFor={`${fieldId}-token`}
        className="mono block text-md text-text-muted mb-1.5"
      >
        signed_token <span className="text-text-muted">(optional)</span>
      </label>
      <textarea
        id={`${fieldId}-token`}
        value={signedToken}
        onChange={(e) => setSignedToken(e.target.value)}
        rows={2}
        spellCheck={false}
        autoComplete="off"
        className="w-full py-2.5 px-3 rounded-sm border border-border bg-bg-input text-text font-code text-sm resize-y mb-5"
      />

      <div
        className="flex gap-2.5 justify-between items-center"
      >
        <button
          type="button"
          className="btn btn--ghost py-1.5 px-2.5 text-sm"
          onClick={onBack}
          disabled={saving}
        >
          ← Back
        </button>
        <button type="submit" className="btn btn--primary" disabled={saving}>
          {saving ? "Connecting…" : "Verify & connect"}
        </button>
      </div>
    </form>
  );
}

