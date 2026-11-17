"use client";
import React from "react";
import Dialog from "../../Dialog";
import { useToast } from "../../ToastProvider";
import { humanizeError } from "@/lib/errorMessage";
import {
  adminAccountsMeta, adminAccountSummary, adminCopyPreview,
  adminSeedAccount, adminWipeAccount, adminCopyAccount,
} from "@/lib/api";
import type {
  AccountTableCounts, AdminAccountSummary, AdminAccountsMeta, AdminUserListItem,
} from "@/lib/types";
import { fieldStyle } from "./adminStyles";
import {
  accountHandles, canConfirmReview, isCopyBlocked, metaView,
  type Action, type ReviewData, type ReviewState,
} from "./accountToolsModel";

/**
 * Admin → Users → "Account tools": seed an account with a major's mock
 * semester, wipe its study data, or copy it to/from the other environment
 * (spec: docs/superpowers/specs/2026-11-08-admin-account-tools-design.md).
 *
 * Two steps. The action list never runs anything: Seed / Wipe / Copy open a
 * REVIEW that reads what the account holds right now (`/summary`, or
 * `/copy-preview` for a copy: both environments) and says, with real counts,
 * what is about to be deleted and what replaces it. Only there does the admin
 * type the account's email (case-insensitive; the user id for an
 * undecryptable row) and press a final button that names the action and its
 * size ("Delete 312 items and seed Biology"). The environment being written
 * leads both steps, in the danger style on production.
 */

const sumCounts = (...maps: (AccountTableCounts | undefined)[]) =>
  maps.reduce<number>(
    (total, m) => total + Object.values(m ?? {}).reduce<number>((s, n) => s + (Number(n) || 0), 0),
    0,
  );

const rows = (n: number) => `${n} row${n === 1 ? "" : "s"}`;

const fmt = (n: number) => n.toLocaleString("en-US");
const plural = (n: number, one: string, many: string) => `${fmt(n)} ${n === 1 ? one : many}`;

/**
 * Summary table → how a person would say it. Order is the order shown.
 * `xp_events` is deliberately absent: XP is shown as the account's total.
 */
const COUNT_LABELS: ReadonlyArray<readonly [table: string, one: string, many: string]> = [
  ["enrollments", "course", "courses"],
  ["assignments", "assignment", "assignments"],
  ["graph_nodes", "concept", "concepts"],
  ["notes", "note", "notes"],
  ["documents", "document", "documents"],
  ["flashcards", "flashcard", "flashcards"],
  ["quiz_attempts", "quiz", "quizzes"],
  ["sessions", "tutor chat", "tutor chats"],
  ["study_guides", "study guide", "study guides"],
  ["user_achievements", "achievement", "achievements"],
];

const countOf = (s: AdminAccountSummary, table: string) => Math.max(0, Number(s.counts?.[table]) || 0);

/** "4 courses, 31 assignments, …, 1,250 XP" — the non-zero parts only. */
function describeSummary(s: AdminAccountSummary): string[] {
  const parts = COUNT_LABELS
    .filter(([t]) => countOf(s, t) > 0)
    .map(([t, one, many]) => plural(countOf(s, t), one, many));
  if (s.total_xp > 0) parts.push(`${fmt(s.total_xp)} XP`);
  return parts;
}

/** The size a confirm button carries: "312 items", else "1,250 XP", else null. */
function summarySize(s: AdminAccountSummary): string | null {
  const items = COUNT_LABELS.reduce((n, [t]) => n + countOf(s, t), 0);
  if (items > 0) return plural(items, "item", "items");
  if (s.total_xp > 0) return `${fmt(s.total_xp)} XP`;
  return null;
}

function envTone(env: string): "prod" | "staging" | "other" {
  const e = env.toLowerCase();
  if (e === "production" || e === "prod") return "prod";
  if (e === "staging") return "staging";
  return "other";
}

const isProd = (env: string | null | undefined) => Boolean(env) && envTone(env as string) === "prod";

const sectionStyle: React.CSSProperties = {
  border: "1px solid var(--border)",
  borderRadius: "var(--r-sm)",
  padding: "14px 16px",
  marginBottom: 12,
};

const sectionTitle: React.CSSProperties = { fontWeight: 600, fontSize: "var(--fs-base)", margin: "0 0 4px" };

const bodyText: React.CSSProperties = {
  margin: "0 0 12px", color: "var(--text-dim)", fontSize: 13, lineHeight: 1.55,
};

const listStyle: React.CSSProperties = {
  listStyle: "none", padding: 0, margin: "8px 0 0", display: "grid", gap: 4, fontSize: 12,
};

function EnvBadge({ env, testid = "admin-account-env", badgeTestid = "admin-account-env-badge", label = "Environment", message }: {
  env: string;
  testid?: string;
  badgeTestid?: string;
  label?: string;
  message?: string;
}) {
  const tone = envTone(env);
  const box: React.CSSProperties =
    tone === "prod"
      ? { background: "var(--err-soft)", color: "var(--err)", borderColor: "var(--err)" }
      : tone === "staging"
        ? { background: "var(--warn-soft)", color: "var(--warn)", borderColor: "transparent" }
        : { background: "var(--bg-soft)", color: "var(--text-dim)", borderColor: "var(--border)" };
  return (
    <div
      data-testid={testid}
      data-env={env}
      style={{
        ...box,
        border: `1px solid ${box.borderColor}`,
        borderRadius: "var(--r-sm)",
        padding: "10px 14px",
        marginBottom: 16,
        display: "flex",
        alignItems: "center",
        gap: 10,
        flexWrap: "wrap",
      }}
    >
      <span className="label-micro" style={{ color: "inherit" }}>{label}</span>
      <strong
        data-testid={badgeTestid}
        style={{ fontFamily: "var(--font-mono)", letterSpacing: "0.06em", fontSize: 14 }}
      >
        {env.toUpperCase()}
      </strong>
      <span style={{ fontSize: 12, color: "inherit" }}>
        {message ?? (tone === "prod"
          ? "Live student data. Every action here writes to the production database."
          : `Actions here write to the ${env} database.`)}
      </span>
    </div>
  );
}

function CourseList({ courses, testid, label }: {
  courses: { code: string; name: string }[];
  testid: string;
  label: string;
}) {
  if (courses.length === 0) return null;
  return (
    <ul data-testid={testid} aria-label={label} style={listStyle}>
      {courses.map((c, i) => (
        <li key={`${c.code}-${i}`} style={{ color: "var(--text-dim)" }}>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--text)" }}>{c.code}</span>
          {c.name ? <> · {c.name}</> : null}
        </li>
      ))}
    </ul>
  );
}

/** One environment's holdings: the counts sentence and the course codes. */
function SummaryBlock({ testid, title, summary, danger, emptyText, missing }: {
  testid: string;
  title: React.ReactNode;
  summary: AdminAccountSummary;
  /** Red frame: this block is what gets deleted on production. */
  danger?: boolean;
  emptyText: string;
  /** Shown instead of the counts when the account doesn't exist there. */
  missing?: React.ReactNode;
}) {
  const parts = describeSummary(summary);
  return (
    <section
      data-testid={testid}
      style={{
        ...sectionStyle,
        flex: "1 1 260px",
        borderColor: danger ? "var(--err)" : "var(--border)",
        background: danger ? "var(--err-soft)" : undefined,
      }}
    >
      <h3 style={sectionTitle}>{title}</h3>
      {!summary.exists && missing ? (
        missing
      ) : summary.empty || parts.length === 0 ? (
        <p data-testid={`${testid}-empty`} style={{ ...bodyText, margin: 0 }}>{emptyText}</p>
      ) : (
        <>
          <p data-testid={`${testid}-counts`} style={{ ...bodyText, margin: 0, color: "var(--text)" }}>
            {parts.join(", ")}
          </p>
          <CourseList
            courses={summary.courses}
            testid={`${testid}-courses`}
            label="Current courses"
          />
        </>
      )}
    </section>
  );
}

/** Above the step: the env badge (hidden while reviewing), a meta error with a retry, or the loading line. */
function renderMetaHeader({ meta, metaError, reviewing, loadMeta }: {
  meta: AdminAccountsMeta | null;
  metaError: string | null;
  reviewing: Action | null;
  loadMeta: (signal: { stale: boolean }) => Promise<void>;
}) {
  return meta ? (
    reviewing ? null : <EnvBadge env={meta.env} />
  ) : metaError ? (
    <div
      data-testid="admin-account-meta-error"
      role="alert"
      style={{ ...sectionStyle, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}
    >
      <span style={{ color: "var(--err)", fontSize: 13 }}>{metaError}</span>
      <button
        type="button"
        className="btn btn--sm"
        data-testid="admin-account-meta-retry"
        onClick={() => void loadMeta({ stale: false })}
      >
        Try again
      </button>
    </div>
  ) : (
    <div data-testid="admin-account-meta-loading" style={{ ...bodyText, marginBottom: 16 }}>
      Loading environment…
    </div>
  );
}

export function AccountToolsDialog({ user, onClose }: {
  user: AdminUserListItem | null;
  onClose: () => void;
}) {
  const toast = useToast();
  const [meta, setMeta] = React.useState<AdminAccountsMeta | null>(null);
  const [metaError, setMetaError] = React.useState<string | null>(null);
  const [major, setMajor] = React.useState("");
  const [reviewing, setReviewing] = React.useState<Action | null>(null);
  const [review, setReview] = React.useState<ReviewState | null>(null);
  const [confirmText, setConfirmText] = React.useState("");
  const [running, setRunning] = React.useState<Action | null>(null);
  const confirmRef = React.useRef<HTMLInputElement>(null);
  const backRef = React.useRef<HTMLButtonElement>(null);
  // Bumped on every review load and on Back: a stale response is dropped.
  const reviewReq = React.useRef(0);
  const confirmId = React.useId();
  const majorId = React.useId();
  const userId = user?.id ?? null;

  const loadMeta = React.useCallback(async (signal: { stale: boolean }) => {
    setMetaError(null);
    try {
      const m = await adminAccountsMeta();
      if (signal.stale) return;
      setMeta(m);
      setMajor((cur) => (cur && m.majors.some((x) => x.key === cur) ? cur : m.majors[0]?.key ?? ""));
    } catch (err) {
      if (signal.stale) return;
      setMetaError(humanizeError(err, "Couldn't load account tools. Try again."));
    }
  }, []);

  // Fresh state per opened account: no review or confirm carries over to the
  // next row, and meta is re-read (the peer can go up or down between opens).
  React.useEffect(() => {
    if (!userId) return;
    reviewReq.current += 1;
    setReviewing(null);
    setReview(null);
    setConfirmText("");
    setRunning(null);
    setMeta(null);
    const signal = { stale: false };
    void loadMeta(signal);
    return () => { signal.stale = true; };
  }, [userId, loadMeta]);

  const loadReview = React.useCallback(async (action: Action) => {
    if (!userId) return;
    const req = ++reviewReq.current;
    setReview({ status: "loading" });
    try {
      const data: ReviewData =
        action === "seed" || action === "wipe"
          ? { kind: "local", summary: await adminAccountSummary(userId) }
          : { kind: "copy", preview: await adminCopyPreview(userId, action) };
      if (reviewReq.current !== req) return;
      setReview({ status: "ready", data });
    } catch (err) {
      if (reviewReq.current !== req) return;
      setReview({
        status: "error",
        message: humanizeError(err, "Couldn't read what this account holds. Try again."),
      });
    }
  }, [userId]);

  const blocked = isCopyBlocked(review);

  // Land on the confirm input once there's something to confirm (Back when
  // the copy is blocked).
  React.useEffect(() => {
    if (review?.status !== "ready") return;
    (blocked ? backRef.current : confirmRef.current)?.focus();
  }, [review, blocked]);

  if (!user) return null;

  const { target, targetIsEmail, who } = accountHandles(user);
  const armed = confirmText.trim().toLowerCase() === target.toLowerCase();
  const busy = running !== null;

  const { selectedMajor, peer, env } = metaView(meta, major);

  const openReview = (action: Action) => {
    if (!meta || busy) return;
    setReviewing(action);
    setConfirmText("");
    void loadReview(action);
  };

  const back = () => {
    if (busy) return;
    reviewReq.current += 1;
    setReviewing(null);
    setReview(null);
    setConfirmText("");
  };

  const ready = review?.status === "ready" ? review.data : null;
  const canConfirm = canConfirmReview({ ready, armed, busy, blocked, meta });

  const run = async () => {
    const action = reviewing;
    if (!action || !canConfirm) return;
    setRunning(action);
    try {
      if (action === "seed") {
        const r = await adminSeedAccount(user.id, major);
        const label = meta?.majors.find((m) => m.key === r.major)?.label ?? r.major;
        toast.success(
          `Seeded ${who} with ${label}: created ${rows(sumCounts(r.created))}, replaced ${rows(sumCounts(r.wiped))}.`,
        );
      } else if (action === "wipe") {
        const r = await adminWipeAccount(user.id);
        toast.success(`Wiped ${who}'s data: removed ${rows(sumCounts(r.wiped))}.`);
      } else {
        const r = await adminCopyAccount(user.id, action);
        const n = rows(sumCounts(r.counts));
        toast.success(
          r.direction === "push"
            ? `Copied ${who} to ${r.peer_env}: ${n}.`
            : `Copied ${who} from ${r.peer_env}: ${n}.`,
        );
      }
      onClose();
    } catch (err) {
      toast.error(humanizeError(err, "That didn't go through. Try again."));
      // A failure can land after a partial wipe: re-read so the review shows
      // what is actually there now.
      void loadReview(action);
    } finally {
      setRunning(null);
    }
  };

  const close = () => { if (!busy) onClose(); };

  // ── step 2: the review ────────────────────────────────────────────────────

  const renderReviewBody = (action: Action, data: ReviewData) => {
    if (data.kind === "local") {
      const s = data.summary;
      return (
        <>
          <SummaryBlock
            testid="admin-account-review-delete"
            title={<>Will delete from <span style={{ fontFamily: "var(--font-mono)" }}>{env.toUpperCase()}</span>:</>}
            summary={s}
            danger={isProd(env) && !s.empty}
            emptyText="This account has no study data yet — nothing will be deleted."
          />
          {action === "seed" && selectedMajor && (
            <section data-testid="admin-account-review-add" style={sectionStyle}>
              <h3 style={sectionTitle}>Will add:</h3>
              <p style={{ ...bodyText, margin: 0 }}>
                A {selectedMajor.label} semester: {plural(selectedMajor.courses.length, "course", "courses")} with
                assignments, notes, documents, flashcards, quizzes, a tutor chat and XP.
              </p>
              <CourseList
                courses={selectedMajor.courses}
                testid="admin-account-review-add-courses"
                label={`${selectedMajor.label} courses`}
              />
            </section>
          )}
          {action === "wipe" && (
            <p data-testid="admin-account-review-kept" style={{ ...bodyText, fontSize: 12 }}>
              <strong>Kept:</strong> the account, profile, settings, roles, and social (rooms, friends). Streak and
              level reset.
            </p>
          )}
        </>
      );
    }
    const { source, destination } = data.preview;
    const missingNote = (side: "source" | "destination") => {
      const where = side === "source" ? source.env : destination.env;
      return (
        <p
          data-testid="admin-account-review-missing"
          role="alert"
          style={{ ...bodyText, margin: 0, color: "var(--err)", fontWeight: 600 }}
        >
          {side === "destination"
            ? `This account hasn't signed in on ${where} yet, so the copy would fail. Have them sign in on ${where} once, then try again.`
            : `This account hasn't signed in on ${where} yet, so there's nothing to copy from it.`}
        </p>
      );
    };
    return (
      <div style={{ display: "flex", gap: 12, flexWrap: "wrap" }}>
        <SummaryBlock
          testid="admin-account-review-destination"
          title={
            <>
              <span style={{ fontFamily: "var(--font-mono)" }}>{destination.env.toUpperCase()}</span> currently has
              {" "}(will be deleted):
            </>
          }
          summary={destination.summary}
          danger={isProd(destination.env) && !destination.summary.empty}
          emptyText={`Nothing yet on ${destination.env} — nothing will be deleted.`}
          missing={missingNote("destination")}
        />
        <SummaryBlock
          testid="admin-account-review-source"
          title={
            <>
              Replaced with, from <span style={{ fontFamily: "var(--font-mono)" }}>{source.env.toUpperCase()}</span>:
            </>
          }
          summary={source.summary}
          emptyText={`${source.env} has no study data for this account — ${destination.env} will be left empty.`}
          missing={missingNote("source")}
        />
      </div>
    );
  };

  const confirmLabel = (action: Action, data: ReviewData): string => {
    if (data.kind === "local") {
      const size = summarySize(data.summary);
      if (action === "seed") {
        const label = selectedMajor?.label ?? major;
        return size ? `Delete ${size} and seed ${label}` : `Seed ${label}`;
      }
      return size ? `Wipe ${size}` : "Wipe data";
    }
    const { source, destination } = data.preview;
    const size = summarySize(destination.summary);
    return size
      ? `Overwrite ${destination.env}'s ${size} with ${source.env}'s data`
      : `Overwrite ${destination.env} with ${source.env}'s data`;
  };

  const runningLabel = (action: Action) =>
    action === "seed" ? "Seeding…" : action === "wipe" ? "Wiping…" : "Copying…";

  const reviewTitle = (action: Action) =>
    action === "seed"
      ? `Review: seed ${selectedMajor?.label ?? major}`
      : action === "wipe"
        ? "Review: wipe study data"
        : action === "push"
          ? `Review: copy to ${peer ?? "peer"}`
          : `Review: copy from ${peer ?? "peer"}`;

  // The environment whose data this action deletes.
  const writtenEnv = (action: Action) => (action === "push" ? peer ?? "peer" : env);

  const renderReview = (action: Action) => {
    const written = writtenEnv(action);
    return (
      <div data-testid="admin-account-review" data-action={action}>
        <EnvBadge
          env={written}
          testid="admin-account-review-target"
          badgeTestid="admin-account-review-target-badge"
          label="Writes to"
          message={
            isProd(written)
              ? "Production. Live student data will be deleted and can't be restored."
              : `This deletes data on ${written}. It can't be undone.`
          }
        />
        <h3 style={{ ...sectionTitle, fontSize: "var(--fs-md, 16px)", margin: "0 0 12px" }}>{reviewTitle(action)}</h3>

        {review?.status === "error" ? (
          <div
            data-testid="admin-account-review-error"
            role="alert"
            style={{ ...sectionStyle, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 12 }}
          >
            <span style={{ color: "var(--err)", fontSize: 13 }}>{review.message}</span>
            <button
              type="button"
              className="btn btn--sm"
              data-testid="admin-account-review-retry"
              onClick={() => void loadReview(action)}
            >
              Try again
            </button>
          </div>
        ) : review?.status === "ready" ? (
          renderReviewBody(action, review.data)
        ) : (
          <p data-testid="admin-account-review-loading" role="status" style={bodyText}>
            Counting what this account holds…
          </p>
        )}

        {ready && !blocked && (
          <label htmlFor={confirmId} style={{ display: "block", margin: "4px 0 16px" }}>
            <span className="label-micro" style={{ display: "block", marginBottom: 4 }}>
              Type {targetIsEmail ? "the account's email" : "the account's user id"}{" "}
              <span style={{ fontFamily: "var(--font-mono)", textTransform: "none", color: "var(--text)" }}>{target}</span>{" "}
              to confirm
            </span>
            <input
              id={confirmId}
              ref={confirmRef}
              data-testid="admin-account-confirm-input"
              value={confirmText}
              onChange={(e) => setConfirmText(e.target.value)}
              autoComplete="off"
              spellCheck={false}
              disabled={busy}
              aria-describedby={`${confirmId}-hint`}
              style={fieldStyle}
            />
            <span id={`${confirmId}-hint`} style={{ display: "block", marginTop: 4, fontSize: 12, color: "var(--text-muted)" }}>
              {armed ? "Confirmed. The button below runs it." : "Not case-sensitive."}
            </span>
          </label>
        )}

        <div style={{ display: "flex", justifyContent: "space-between", gap: 10, flexWrap: "wrap" }}>
          <button
            type="button"
            className="btn"
            ref={backRef}
            data-testid="admin-account-review-back"
            disabled={busy}
            onClick={back}
          >
            Back
          </button>
          {ready && (
            <button
              type="button"
              className="btn btn--danger"
              data-testid="admin-account-review-confirm"
              disabled={!canConfirm}
              onClick={() => void run()}
            >
              {running === action ? runningLabel(action) : confirmLabel(action, ready)}
            </button>
          )}
        </div>
      </div>
    );
  };

  // ── step 1: the action list ───────────────────────────────────────────────

  const canOpen = meta !== null && !busy;

  const renderActions = () => (
    <>
      <p style={{ ...bodyText, fontSize: 12 }}>
        Nothing runs from this list. Each action first shows what it will delete, with counts, and asks you to
        confirm.
      </p>

      <section aria-labelledby={`${majorId}-title`} style={sectionStyle}>
        <h3 id={`${majorId}-title`} style={sectionTitle}>Seed with a major&apos;s mock data</h3>
        <p style={bodyText}>
          <strong>Replaces</strong> this account&apos;s courses and study data (enrollments, documents, notes,
          flashcards, quizzes, tutor sessions, knowledge graph, XP) with a realistic semester of four courses for
          the chosen major. Nothing is stacked: whatever is there now is wiped first.
        </p>
        <div style={{ display: "flex", gap: 10, alignItems: "flex-end", flexWrap: "wrap" }}>
          <label htmlFor={majorId} style={{ flex: "1 1 220px" }}>
            <span className="label-micro" style={{ display: "block", marginBottom: 4 }}>Major</span>
            <select
              id={majorId}
              data-testid="admin-account-major"
              value={major}
              onChange={(e) => setMajor(e.target.value)}
              disabled={busy || !meta || meta.majors.length === 0}
              style={fieldStyle}
            >
              {(meta?.majors ?? []).map((m) => (
                <option key={m.key} value={m.key}>{m.label}</option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="btn btn--primary"
            data-testid="admin-account-seed"
            disabled={!canOpen || !selectedMajor}
            onClick={() => openReview("seed")}
          >
            {selectedMajor ? `Seed ${selectedMajor.label}…` : "Seed…"}
          </button>
        </div>
        {selectedMajor && (
          <CourseList
            courses={selectedMajor.courses}
            testid="admin-account-major-courses"
            label={`${selectedMajor.label} courses`}
          />
        )}
      </section>

      <section aria-labelledby={`${majorId}-wipe-title`} style={sectionStyle}>
        <h3 id={`${majorId}-wipe-title`} style={sectionTitle}>Wipe study data</h3>
        <p style={bodyText}>
          Removes enrollments and gradebook, documents (and their indexed chunks), notes, flashcards, study
          guides, quizzes, tutor sessions, the knowledge graph, XP and achievements, and resets streak and level.
          <br />
          <strong>Kept:</strong> the account, profile, settings, roles, and social (rooms, friends).
        </p>
        <button
          type="button"
          className="btn btn--danger"
          data-testid="admin-account-wipe"
          disabled={!canOpen}
          onClick={() => openReview("wipe")}
        >
          Wipe data…
        </button>
      </section>

      <section aria-labelledby={`${majorId}-copy-title`} style={{ ...sectionStyle, marginBottom: 20 }}>
        <h3 id={`${majorId}-copy-title`} style={sectionTitle}>Copy between environments</h3>
        {!meta ? null : !meta.sync.configured ? (
          <p data-testid="admin-account-copy-unconfigured" style={{ ...bodyText, margin: 0, color: "var(--text-muted)" }}>
            Copying isn&apos;t configured on this environment.
          </p>
        ) : (
          <>
            <p style={bodyText}>
              Overwrites the <strong>destination&apos;s</strong> data for this account with the source&apos;s
              copy. It doesn&apos;t merge: the destination is wiped first. The account must already exist on the
              other environment (they&apos;ve signed in there once).
            </p>
            {peer === null && (
              <p data-testid="admin-account-copy-unreachable" role="status" style={{ ...bodyText, color: "var(--warn)" }}>
                The other environment is unreachable right now, so copying is unavailable.
              </p>
            )}
            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button
                type="button"
                className="btn"
                data-testid="admin-account-copy-push"
                disabled={!canOpen || peer === null}
                onClick={() => openReview("push")}
                title={peer ? `Overwrite ${peer}'s data for this account with ${meta.env}'s` : undefined}
              >
                {`Copy to ${peer ?? "peer"}…`}
              </button>
              <button
                type="button"
                className="btn"
                data-testid="admin-account-copy-pull"
                disabled={!canOpen || peer === null}
                onClick={() => openReview("pull")}
                title={peer ? `Overwrite ${meta.env}'s data for this account with ${peer}'s` : undefined}
              >
                {`Copy from ${peer ?? "peer"}…`}
              </button>
            </div>
          </>
        )}
      </section>

      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <button
          type="button"
          className="btn"
          data-testid="admin-account-close"
          disabled={busy}
          onClick={onClose}
        >
          Close
        </button>
      </div>
    </>
  );

  return (
    <Dialog
      open
      onClose={close}
      dismissible={!busy}
      size="lg"
      title={`Account tools: ${who}`}
    >
      <div data-testid="admin-account-tools">
        {renderMetaHeader({ meta, metaError, reviewing, loadMeta })}

        {reviewing && meta ? renderReview(reviewing) : renderActions()}
      </div>
    </Dialog>
  );
}
