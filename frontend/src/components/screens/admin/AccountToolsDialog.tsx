"use client";
import React from "react";
import Dialog from "../../Dialog";
import { useToast } from "../../ToastProvider";
import { humanizeError } from "@/lib/errorMessage";
import {
  adminAccountsMeta, adminSeedAccount, adminWipeAccount, adminCopyAccount,
} from "@/lib/api";
import type {
  AccountTableCounts, AdminAccountsMeta, AdminUserListItem,
} from "@/lib/types";
import { fieldStyle } from "./adminStyles";

/**
 * Admin → Users → "Account tools": seed an account with a major's mock
 * semester, wipe its study data, or copy it to/from the other environment
 * (spec: docs/superpowers/specs/2026-11-08-admin-account-tools-design.md).
 *
 * The same buttons exist on production, so the dialog leads with the
 * environment it is about to write to, and every action stays disabled until
 * the admin types the target account's email (case-insensitive). An account
 * whose email can't be read (`undecryptable`) is confirmed by its user id.
 */

type Action = "seed" | "wipe" | "push" | "pull";

const sumCounts = (...maps: (AccountTableCounts | undefined)[]) =>
  maps.reduce<number>(
    (total, m) => total + Object.values(m ?? {}).reduce<number>((s, n) => s + (Number(n) || 0), 0),
    0,
  );

const rows = (n: number) => `${n} row${n === 1 ? "" : "s"}`;

function envTone(env: string): "prod" | "staging" | "other" {
  const e = env.toLowerCase();
  if (e === "production" || e === "prod") return "prod";
  if (e === "staging") return "staging";
  return "other";
}

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

function EnvBadge({ env }: { env: string }) {
  const tone = envTone(env);
  const label = env.toUpperCase();
  const box: React.CSSProperties =
    tone === "prod"
      ? { background: "var(--err-soft)", color: "var(--err)", borderColor: "var(--err)" }
      : tone === "staging"
        ? { background: "var(--warn-soft)", color: "var(--warn)", borderColor: "transparent" }
        : { background: "var(--bg-soft)", color: "var(--text-dim)", borderColor: "var(--border)" };
  return (
    <div
      data-testid="admin-account-env"
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
      <span className="label-micro" style={{ color: "inherit" }}>Environment</span>
      <strong
        data-testid="admin-account-env-badge"
        style={{ fontFamily: "var(--font-mono)", letterSpacing: "0.06em", fontSize: 14 }}
      >
        {label}
      </strong>
      <span style={{ fontSize: 12, color: "inherit" }}>
        {tone === "prod"
          ? "Live student data. Every action here writes to the production database."
          : `Actions here write to the ${env} database.`}
      </span>
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
  const [confirmText, setConfirmText] = React.useState("");
  const [running, setRunning] = React.useState<Action | null>(null);
  const confirmRef = React.useRef<HTMLInputElement>(null);
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

  // Fresh state per opened account: the confirm never carries over to the
  // next row, and meta is re-read (the peer can go up or down between opens).
  React.useEffect(() => {
    if (!userId) return;
    setConfirmText("");
    setRunning(null);
    setMeta(null);
    const signal = { stale: false };
    void loadMeta(signal);
    return () => { signal.stale = true; };
  }, [userId, loadMeta]);

  if (!user) return null;

  // An undecryptable row has no email to type; its id is the next-best
  // unambiguous handle.
  const target = (user.email ?? "").trim() || user.id;
  const targetIsEmail = Boolean(user.email && user.email.trim());
  const who = user.name || user.email || user.id;
  const armed = confirmText.trim().toLowerCase() === target.toLowerCase();
  const busy = running !== null;
  const canAct = armed && !busy && meta !== null;

  const selectedMajor = meta?.majors.find((m) => m.key === major) ?? null;
  const peer = meta?.sync.peer_env ?? null;

  const run = async (action: Action) => {
    if (!canAct) return;
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
    } finally {
      setRunning(null);
    }
  };

  const close = () => { if (!busy) onClose(); };

  return (
    <Dialog
      open
      onClose={close}
      dismissible={!busy}
      size="lg"
      title={`Account tools: ${who}`}
      initialFocusRef={confirmRef}
    >
      <div data-testid="admin-account-tools">
        {meta ? (
          <EnvBadge env={meta.env} />
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
        )}

        <label htmlFor={confirmId} style={{ display: "block", marginBottom: 16 }}>
          <span className="label-micro" style={{ display: "block", marginBottom: 4 }}>
            Type {targetIsEmail ? "the account's email" : "the account's user id"}{" "}
            <span style={{ fontFamily: "var(--font-mono)", textTransform: "none", color: "var(--text)" }}>{target}</span>{" "}
            to enable these actions
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
            {armed ? "Confirmed. Each action below runs immediately." : "Not case-sensitive."}
          </span>
        </label>

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
              disabled={!canAct || !selectedMajor}
              onClick={() => void run("seed")}
            >
              {running === "seed" ? "Seeding…" : selectedMajor ? `Seed ${selectedMajor.label}` : "Seed"}
            </button>
          </div>
          {selectedMajor && selectedMajor.courses.length > 0 && (
            <ul
              data-testid="admin-account-major-courses"
              aria-label={`${selectedMajor.label} courses`}
              style={{ listStyle: "none", padding: 0, margin: "10px 0 0", display: "grid", gap: 4, fontSize: 12 }}
            >
              {selectedMajor.courses.map((c) => (
                <li key={c.code} style={{ color: "var(--text-dim)" }}>
                  <span style={{ fontFamily: "var(--font-mono)", color: "var(--text)" }}>{c.code}</span>
                  {c.name ? <> · {c.name}</> : null}
                </li>
              ))}
            </ul>
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
            disabled={!canAct}
            onClick={() => void run("wipe")}
          >
            {running === "wipe" ? "Wiping…" : "Wipe data"}
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
                  disabled={!canAct || peer === null}
                  onClick={() => void run("push")}
                  title={peer ? `Overwrite ${peer}'s data for this account with ${meta.env}'s` : undefined}
                >
                  {running === "push" ? "Copying…" : `Copy to ${peer ?? "peer"}`}
                </button>
                <button
                  type="button"
                  className="btn"
                  data-testid="admin-account-copy-pull"
                  disabled={!canAct || peer === null}
                  onClick={() => void run("pull")}
                  title={peer ? `Overwrite ${meta.env}'s data for this account with ${peer}'s` : undefined}
                >
                  {running === "pull" ? "Copying…" : `Copy from ${peer ?? "peer"}`}
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
      </div>
    </Dialog>
  );
}
