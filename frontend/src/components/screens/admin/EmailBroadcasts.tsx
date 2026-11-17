"use client";
import React from "react";

import Dialog from "@/components/Dialog";
import { AdminTableSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import {
  adminEmailAudiences,
  adminEmailStatus,
  adminListBroadcasts,
  adminPreviewBroadcast,
  adminResumeBroadcast,
  adminSendBroadcast,
  adminSendTestBroadcast,
} from "@/lib/api";
import { extractErrorDetail } from "@/lib/errorMessage";
import type {
  EmailAudience, EmailAudienceKey, EmailBroadcast, EmailBroadcastPreview, EmailStatus, EmailVariable,
} from "@/lib/types";

import { fieldStyle, tdStyle, thStyle } from "./adminStyles";
import {
  audienceLabel, broadcastChipClass, broadcastDate, broadcastStatusLabel, deriveSendGate, isAnySending,
  people, spliceAtSelection, token, variableTitle,
} from "./emailBroadcastHelpers";
import { EmailNotConfiguredBanner } from "./EmailNotConfiguredBanner";

/**
 * Admin "Email" tab: compose a plain-text broadcast, preview it, send a test
 * to yourself, then send it to an audience behind a typed confirmation. The
 * send is accepted (202) and delivered in the background, so the history
 * table polls while any broadcast is still `sending`. A run the server marks
 * `stale` (no heartbeat: a deploy killed it) shows as "stalled", and it or a
 * `failed`/`partial` one gets a Resume button, which re-runs it through the
 * per-recipient dedupe so nobody gets it twice.
 *
 * The preview is the real email: the draft is debounced to
 * `POST /email/broadcasts/preview`, and the server-rendered HTML document is
 * shown in a sandboxed iframe (no scripts, no same-origin), so what the
 * admin sees is exactly what goes out.
 *
 * Personalization: the admin can write `{{key}}` / `{{key|fallback}}` in the
 * subject or body. The "Personalize" chips (from `/email/status` `variables`)
 * insert a variable at the caret of the last-focused field. The preview and
 * the test send fill in the admin's own values; a real send fills in each
 * recipient's. An unknown variable comes back on the preview as
 * `unknown_variables`, and both sends stay disabled until it's fixed (the
 * server 422s them anyway).
 */

export const SUBJECT_MAX = 200;
export const BODY_MAX = 20000;
export const POLL_MS = 5000;
export const PREVIEW_DEBOUNCE_MS = 350;
/** Fixed: auto-sizing would need a same-origin frame. The frame scrolls past this. */
const PREVIEW_HEIGHT = 720;

/**
 * What the server said about a failed send. A 422 from the unknown-variable
 * check is a FastAPI validation error, `{detail: [{msg: "Value error, Unknown
 * variable {{x}}. Use one of: …"}]}`; every msg is kept (subject and body can
 * each fail) and Pydantic's "Value error, " prefix dropped. `humanizeError`
 * would discard these (braces, length), but here the braces are the point.
 */
export function sendErrorText(err: unknown): string {
  const body = (err as { body?: unknown } | null)?.body;
  const detail = body !== null && typeof body === "object" ? (body as { detail?: unknown }).detail : undefined;
  if (Array.isArray(detail)) {
    const msgs = detail
      .map((d) => (d !== null && typeof d === "object" ? (d as { msg?: unknown }).msg : undefined))
      .filter((m): m is string => typeof m === "string" && m.trim().length > 0)
      .map((m) => m.trim().replace(/^Value error,\s*/i, ""));
    if (msgs.length > 0) return [...new Set(msgs)].join(" ");
  }
  return extractErrorDetail(err).detail ?? String(err);
}

type ComposeField = "subject" | "body";
type Toast = ReturnType<typeof useToast>;
type Setter<T> = React.Dispatch<React.SetStateAction<T>>;
type Preview = ReturnType<typeof useBroadcastPreview>;

/** The debounced server render of the trimmed draft. */
function useBroadcastPreview(subject: string, body: string) {
  const [preview, setPreview] = React.useState<EmailBroadcastPreview | null>(null);
  // The trimmed draft the shown preview was rendered for. Its filled-in
  // subject is only shown, and both sends are only enabled, while it still
  // matches the draft: otherwise `unknown_variables` may describe old text.
  const [previewFor, setPreviewFor] = React.useState<{ subject: string; body: string } | null>(null);
  const [previewError, setPreviewError] = React.useState(false);
  // Only the latest preview request may update the pane; bumped on every
  // draft change (and on unmount) so an older, slower response is dropped.
  const previewSeq = React.useRef(0);
  const previewSubject = subject.trim();
  const previewBody = body.trim();
  React.useEffect(() => {
    const seq = ++previewSeq.current;
    const id = window.setTimeout(() => {
      adminPreviewBroadcast({ subject: previewSubject, body: previewBody }).then(
        (r) => {
          if (seq !== previewSeq.current) return;
          setPreview(r);
          setPreviewFor({ subject: previewSubject, body: previewBody });
          setPreviewError(false);
        },
        () => {
          if (seq !== previewSeq.current) return;
          setPreviewError(true); // keep the last good render on screen
        },
      );
    }, PREVIEW_DEBOUNCE_MS);
    return () => {
      window.clearTimeout(id);
      previewSeq.current += 1;
    };
  }, [previewSubject, previewBody]);
  return { preview, previewFor, previewError, previewSubject };
}

interface Draft {
  subject: string;
  body: string;
  setSubject: Setter<string>;
  setBody: Setter<string>;
}

/** The Personalize chips: insert `{{key}}` at the caret of the last-focused field. */
function useVariableInsertion({ subject, body, setSubject, setBody }: Draft, toast: Toast) {
  const subjectRef = React.useRef<HTMLInputElement | null>(null);
  const bodyRef = React.useRef<HTMLTextAreaElement | null>(null);
  // Where a Personalize chip inserts: the field focused last (body until then).
  const lastField = React.useRef<ComposeField>("body");
  // Set by insertVariable, applied once the new value has rendered.
  const pendingCaret = React.useRef<{ field: ComposeField; pos: number } | null>(null);
  React.useLayoutEffect(() => {
    const p = pendingCaret.current;
    if (!p) return;
    pendingCaret.current = null;
    const el = p.field === "subject" ? subjectRef.current : bodyRef.current;
    if (!el) return;
    el.focus();
    el.setSelectionRange(p.pos, p.pos);
  }, [subject, body]);

  const insertVariable = (key: string) => {
    const field = lastField.current;
    const isSubject = field === "subject";
    const el = isSubject ? subjectRef.current : bodyRef.current;
    const max = isSubject ? SUBJECT_MAX : BODY_MAX;
    const text = token(key);
    const { start, next } = spliceAtSelection(isSubject ? subject : body, el, text);
    if (next.length > max) {
      toast.warn(`No room for ${text}: the ${field} is limited to ${max} characters.`);
      el?.focus();
      return;
    }
    pendingCaret.current = { field, pos: start + text.length };
    if (isSubject) setSubject(next);
    else setBody(next);
  };
  return { subjectRef, bodyRef, lastField, insertVariable };
}
type Insertion = ReturnType<typeof useVariableInsertion>;

/** Status, audiences and the broadcast history: loaded once, polled while sending. */
function useEmailTabData(toast: Toast) {
  const [loading, setLoading] = React.useState(true);
  const [status, setStatus] = React.useState<EmailStatus | null>(null);
  const [audiences, setAudiences] = React.useState<EmailAudience[]>([]);
  const [broadcasts, setBroadcasts] = React.useState<EmailBroadcast[]>([]);

  React.useEffect(() => {
    let alive = true;
    Promise.allSettled([adminEmailStatus(), adminEmailAudiences(), adminListBroadcasts()]).then(
      ([s, a, b]) => {
        if (!alive) return;
        if (s.status === "fulfilled") setStatus(s.value);
        if (a.status === "fulfilled") setAudiences(a.value.audiences || []);
        else toast.error(`Couldn't load audiences: ${String(a.reason)}`);
        if (b.status === "fulfilled") setBroadcasts(b.value.broadcasts || []);
        else toast.error(`Couldn't load broadcast history: ${String(b.reason)}`);
        setLoading(false);
      },
    );
    return () => { alive = false; };
  }, [toast]);

  // Bumped whenever this tab changes the history itself (a send, a resume),
  // so a poll that was already in flight when it did can't overwrite the new
  // row with its older list (and stop the polling with it).
  const historySeq = React.useRef(0);

  // Poll the history only while something is still going out (a stale run
  // isn't going anywhere until it's resumed).
  const anySending = isAnySending(broadcasts);
  React.useEffect(() => {
    if (!anySending) return;
    const id = window.setInterval(() => {
      const seq = historySeq.current;
      adminListBroadcasts().then(
        (r) => { if (seq === historySeq.current) setBroadcasts(r.broadcasts || []); },
        () => { /* transient; the next tick retries */ },
      );
    }, POLL_MS);
    return () => window.clearInterval(id);
  }, [anySending]);

  const upsertBroadcast = (row: EmailBroadcast) => {
    historySeq.current += 1;
    setBroadcasts((prev) => [row, ...prev.filter((b) => b.id !== row.id)]);
  };
  return { loading, status, audiences, broadcasts, upsertBroadcast };
}
type TabData = ReturnType<typeof useEmailTabData>;

/** Resume a stalled/failed/partial run; one at a time. */
function useResume(upsertBroadcast: TabData["upsertBroadcast"], toast: Toast) {
  const [resuming, setResuming] = React.useState<string | null>(null);
  const resume = async (b: EmailBroadcast) => {
    setResuming(b.id);
    try {
      const r = await adminResumeBroadcast(b.id);
      upsertBroadcast(r.broadcast);
      toast.success(`Resuming “${b.subject}”. Anyone it already reached is skipped.`);
    } catch (err) {
      toast.error(`Resume failed: ${sendErrorText(err)}`);
    } finally {
      setResuming(null);
    }
  };
  return { resuming, resume };
}

/** Audience choice, the test send, and the real send behind its typed confirmation. */
function useSendFlow(draft: Draft, data: TabData, pv: Preview, toast: Toast) {
  const { subject, body, setSubject, setBody } = draft;
  const [audience, setAudience] = React.useState<EmailAudienceKey | null>(null);
  const [testing, setTesting] = React.useState(false);
  const [sending, setSending] = React.useState(false);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [confirmText, setConfirmText] = React.useState("");
  const confirmInputRef = React.useRef<HTMLInputElement | null>(null);

  const gate = deriveSendGate({
    audiences: data.audiences, audience, subject, body,
    preview: pv.preview, previewFor: pv.previewFor, status: data.status, sending, confirmText,
  });

  const sendTest = async () => {
    setTesting(true);
    try {
      const r = await adminSendTestBroadcast({ subject: subject.trim(), body: body.trim() });
      const msg = `Test email to ${r.to}: ${r.status}`;
      if (r.status === "sent" || r.status === "queued") toast.success(msg);
      else toast.warn(msg);
    } catch (err) {
      toast.error(`Test send failed: ${sendErrorText(err)}`);
    } finally {
      setTesting(false);
    }
  };

  const openConfirm = () => {
    setConfirmText("");
    setConfirmOpen(true);
  };

  const send = async () => {
    if (!audience || !gate.canSend || !gate.confirmOk) return;
    setSending(true);
    try {
      const r = await adminSendBroadcast({ subject: subject.trim(), body: body.trim(), audience });
      data.upsertBroadcast(r.broadcast);
      toast.success(`Sending to ${people(gate.n)}. Progress shows in History below.`);
      setSubject("");
      setBody("");
      setConfirmOpen(false);
    } catch (err) {
      toast.error(`Send failed: ${sendErrorText(err)}`);
    } finally {
      setSending(false);
    }
  };

  return {
    gate, audience, setAudience, testing, sending, confirmOpen, setConfirmOpen, confirmText, setConfirmText,
    confirmInputRef, sendTest, openConfirm, send,
  };
}
type SendFlow = ReturnType<typeof useSendFlow>;

export function EmailBroadcastsTab() {
  const toast = useToast();
  const [subject, setSubject] = React.useState("");
  const [body, setBody] = React.useState("");
  const draft: Draft = { subject, body, setSubject, setBody };
  const pv = useBroadcastPreview(subject, body);
  const insertion = useVariableInsertion(draft, toast);
  const data = useEmailTabData(toast);
  const { resuming, resume } = useResume(data.upsertBroadcast, toast);
  const flow = useSendFlow(draft, data, pv, toast);

  if (data.loading) return <AdminTableSkeleton />;

  return (
    <>
      {flow.gate.notConfigured && <EmailNotConfiguredBanner />}

      <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 340px), 1fr))", gap: 16, marginBottom: 16 }}>
        <ComposeCard draft={draft} insertion={insertion} data={data} flow={flow} />
        <PreviewCard pv={pv} />
      </div>

      <HistoryCard data={data} resuming={resuming} onResume={resume} />

      <ConfirmSendDialog subject={subject} flow={flow} />
    </>
  );
}

function ComposeCard({ draft, insertion, data, flow }: {
  draft: Draft; insertion: Insertion; data: TabData; flow: SendFlow;
}) {
  const { subject, body, setSubject, setBody } = draft;
  const { subjectRef, bodyRef, lastField: lastFieldRef } = insertion;
  return (
    <div className="card" style={{ padding: "var(--pad-lg)" }}>
      <div className="label-micro" style={{ marginBottom: 10 }}>Compose</div>

      <label style={{ display: "block", marginBottom: 12 }}>
        <span style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
          <span className="label-micro">Subject</span>
          <span className="label-micro" data-testid="email-subject-count">{subject.length}/{SUBJECT_MAX}</span>
        </span>
        <input
          ref={subjectRef}
          data-testid="email-subject"
          value={subject}
          maxLength={SUBJECT_MAX}
          onFocus={() => { lastFieldRef.current = "subject"; }}
          onChange={(e) => setSubject(e.target.value)}
          style={fieldStyle}
        />
      </label>

      <div style={{ marginBottom: 12 }}>
        <label style={{ display: "block" }}>
          <span style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
            <span className="label-micro">Body</span>
            <span className="label-micro" data-testid="email-body-count">{body.length}/{BODY_MAX}</span>
          </span>
          <textarea
            ref={bodyRef}
            data-testid="email-body"
            value={body}
            maxLength={BODY_MAX}
            rows={10}
            onFocus={() => { lastFieldRef.current = "body"; }}
            onChange={(e) => setBody(e.target.value)}
            style={{ ...fieldStyle, resize: "vertical", minHeight: 160 }}
          />
        </label>
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 4 }}>
          Plain text. Blank lines make paragraphs; links are clickable.
          Variables like {token("first_name")} are filled in for each person. Put{" "}
          {token("signin_link")} on its own line for a button.
        </div>
        <VariableChips variables={data.status?.variables ?? []} onInsert={insertion.insertVariable} />
        <UnknownVariablesNotice unknownVars={flow.gate.unknownVars} />
      </div>

      <AudienceFieldset audiences={data.audiences} audience={flow.audience} onChange={flow.setAudience} />

      <ComposeActions flow={flow} />
      {data.status?.from_address && (
        <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 10 }}>
          From {data.status.from_address}
        </div>
      )}
    </div>
  );
}

function VariableChips({ variables, onInsert }: { variables: EmailVariable[]; onInsert: (key: string) => void }) {
  if (variables.length === 0) return null;
  return (
    <div
      data-testid="email-variables"
      style={{ display: "flex", flexWrap: "wrap", alignItems: "center", gap: 6, marginTop: 8 }}
    >
      <span className="label-micro">Personalize:</span>
      {variables.map((v) => (
        <button
          key={v.key}
          type="button"
          className="chip"
          data-testid={`email-variable-${v.key}`}
          title={variableTitle(v)}
          onClick={() => onInsert(v.key)}
          style={{ cursor: "pointer", textTransform: "none" }}
        >
          {v.label}
        </button>
      ))}
    </div>
  );
}

function UnknownVariablesNotice({ unknownVars }: { unknownVars: string[] }) {
  if (unknownVars.length === 0) return null;
  return (
    <div
      data-testid="email-unknown-variables"
      role="status"
      style={{
        marginTop: 10, padding: "8px 10px", borderRadius: "var(--r-sm)", fontSize: 12,
        background: "var(--warn-soft)", color: "var(--warn)", overflowWrap: "anywhere",
      }}
    >
      Unknown {unknownVars.length === 1 ? "variable" : "variables"} {unknownVars.map(token).join(", ")}.
      {" "}Check the spelling, or pick one from Personalize. Sending is off until it&apos;s fixed.
    </div>
  );
}

function AudienceFieldset({ audiences, audience, onChange }: {
  audiences: EmailAudience[]; audience: EmailAudienceKey | null; onChange: (key: EmailAudienceKey) => void;
}) {
  return (
    <fieldset style={{ border: 0, padding: 0, margin: "0 0 16px" }}>
      <legend className="label-micro" style={{ marginBottom: 6 }}>Audience</legend>
      {audiences.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>No audiences available.</div>
      )}
      {audiences.map((a) => (
        <label
          key={a.key}
          style={{
            display: "flex", alignItems: "center", gap: 8, padding: "6px 0", fontSize: 13, cursor: "pointer",
          }}
        >
          <input
            type="radio"
            name="email-audience"
            data-testid={`email-audience-${a.key}`}
            value={a.key}
            checked={audience === a.key}
            onChange={() => onChange(a.key)}
          />
          <span style={{ flex: 1 }}>{a.label}</span>
          <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-dim)" }}>{a.count}</span>
        </label>
      ))}
    </fieldset>
  );
}

function ComposeActions({ flow }: { flow: SendFlow }) {
  const { gate, testing, sending } = flow;
  return (
    <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
      <button
        type="button"
        className="btn btn--ghost btn--sm"
        data-testid="email-send-test"
        disabled={!gate.hasDraft || !gate.previewCurrent || gate.hasUnknown || testing}
        onClick={() => void flow.sendTest()}
      >
        {testing ? "Sending test…" : "Send test to me"}
      </button>
      <button
        type="button"
        className="btn btn--primary btn--sm"
        data-testid="email-send"
        disabled={!gate.canSend}
        onClick={flow.openConfirm}
      >
        {sending ? "Sending…" : `Send to ${people(gate.n)}`}
      </button>
    </div>
  );
}

function PreviewCard({ pv }: { pv: Preview }) {
  const { preview, previewFor, previewError, previewSubject } = pv;
  return (
    <div className="card" style={{ padding: "var(--pad-lg)", minWidth: 0 }}>
      <div className="label-micro" style={{ marginBottom: 10 }}>Preview</div>
      <div
        data-testid="email-preview"
        style={{
          border: "1px solid var(--border)", borderRadius: "var(--r-md)", overflow: "hidden",
          background: "var(--bg-subtle)", fontSize: 14,
        }}
      >
        <div
          data-testid="email-preview-subject"
          style={{ fontWeight: 600, padding: "12px 16px", borderBottom: "1px solid var(--border)", overflowWrap: "anywhere" }}
        >
          {previewSubject
            ? (preview && previewFor?.subject === previewSubject ? preview.subject : previewSubject)
            : <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>(no subject)</span>}
        </div>
        {preview ? (
          <iframe
            data-testid="email-preview-frame"
            title="Email preview"
            srcDoc={preview.html}
            sandbox="allow-popups allow-popups-to-escape-sandbox"
            referrerPolicy="no-referrer"
            style={{ display: "block", width: "100%", height: PREVIEW_HEIGHT, border: 0, background: "#fff" }}
          />
        ) : (
          <div style={{ padding: 16, fontSize: 13, color: "var(--text-muted)" }}>
            {previewError ? (
              <span data-testid="email-preview-error">Couldn&apos;t load the preview.</span>
            ) : (
              "Loading preview…"
            )}
          </div>
        )}
      </div>
      {preview && previewError && (
        <div data-testid="email-preview-error" role="status" style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 8 }}>
          Couldn&apos;t load the preview. Showing the last version.
        </div>
      )}
    </div>
  );
}

function HistoryCard({ data, resuming, onResume }: {
  data: TabData; resuming: string | null; onResume: (b: EmailBroadcast) => Promise<void>;
}) {
  const { broadcasts, audiences } = data;
  return (
    <div className="card" style={{ padding: 0 }} data-testid="email-history">
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
        <div className="label-micro">History · {broadcasts.length}</div>
      </div>
      {broadcasts.length === 0 ? (
        <div style={{ padding: 28, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>
          No broadcasts yet.
        </div>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
            <thead>
              <tr style={{ background: "var(--bg-subtle)" }}>
                {["Subject", "Audience", "Status", "Delivered", "Date"].map((h) => (
                  <th key={h} style={thStyle}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {broadcasts.map((b) => (
                <HistoryRow key={b.id} b={b} audiences={audiences} resuming={resuming} onResume={onResume} />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function HistoryRow({ b, audiences, resuming, onResume }: {
  b: EmailBroadcast; audiences: EmailAudience[]; resuming: string | null; onResume: (b: EmailBroadcast) => Promise<void>;
}) {
  return (
    <tr data-testid={`email-history-row-${b.id}`} style={{ borderTop: "1px solid var(--border)" }}>
      <td style={{ ...tdStyle, fontWeight: 500, overflowWrap: "anywhere" }}>{b.subject}</td>
      <td style={{ ...tdStyle, color: "var(--text-dim)" }}>{audienceLabel(audiences, b.audience)}</td>
      <td style={tdStyle}>
        <span className={broadcastChipClass(b.status)} data-testid={`email-history-status-${b.id}`}>
          {broadcastStatusLabel(b)}
        </span>
        {b.resumable && (
          <button
            type="button"
            className="btn btn--ghost btn--sm"
            data-testid={`email-history-resume-${b.id}`}
            title="Send it to everyone in this audience it hasn't reached yet."
            disabled={resuming !== null}
            onClick={() => void onResume(b)}
            style={{ marginLeft: 8 }}
          >
            {resuming === b.id ? "Resuming…" : "Resume"}
          </button>
        )}
      </td>
      <td style={{ ...tdStyle, whiteSpace: "nowrap" }}>
        <span style={{ fontFamily: "var(--font-mono)" }}>{b.sent_count}/{b.recipient_count}</span>
        <DeliveryOutcome failed={b.failed_count} skipped={b.skipped_count} />
      </td>
      <td style={{ ...tdStyle, color: "var(--text-muted)", whiteSpace: "nowrap" }}>
        {broadcastDate(b)}
      </td>
    </tr>
  );
}

/** "N failed · M skipped" under the delivered count, when either is non-zero. */
function DeliveryOutcome({ failed, skipped }: { failed: number; skipped: number }) {
  if (!(failed > 0 || skipped > 0)) return null;
  return (
    <span style={{ display: "block", fontSize: 11, color: "var(--text-muted)" }}>
      {failed > 0 && <span style={{ color: "var(--warn)" }}>{failed} failed</span>}
      {failed > 0 && skipped > 0 && " · "}
      {skipped > 0 && <span>{skipped} skipped</span>}
    </span>
  );
}

function ConfirmSendDialog({ subject, flow }: { subject: string; flow: SendFlow }) {
  const { gate, sending, confirmOpen, setConfirmOpen, confirmText, setConfirmText, confirmInputRef, send } = flow;
  const { n, selectedAudience, notConfigured, canSend, confirmOk } = gate;
  return (
    <Dialog
      open={confirmOpen}
      onClose={() => { if (!sending) setConfirmOpen(false); }}
      size="sm"
      title={`Email ${people(n)}?`}
      initialFocusRef={confirmInputRef}
    >
      <p className="flags__confirm-text" style={{ marginBottom: 12 }}>
        This sends &ldquo;{subject.trim()}&rdquo; to {people(n)} in <strong>{selectedAudience?.label}</strong>.
        These are real inboxes and it can&apos;t be undone.
        {notConfigured && " Email isn't configured, so the broadcast will be recorded but nothing is delivered."}
      </p>
      <label style={{ display: "block", marginBottom: 20 }}>
        <span className="label-micro" style={{ display: "block", marginBottom: 4 }}>
          Type {n} or SEND to confirm
        </span>
        <input
          ref={confirmInputRef}
          data-testid="email-send-confirm-input"
          value={confirmText}
          onChange={(e) => setConfirmText(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter" && confirmOk) void send(); }}
          autoComplete="off"
          style={fieldStyle}
        />
      </label>
      <div className="flags__confirm-actions">
        <button
          type="button"
          className="btn"
          data-testid="email-send-cancel"
          disabled={sending}
          onClick={() => setConfirmOpen(false)}
        >
          Cancel
        </button>
        <button
          type="button"
          className="btn btn--primary"
          data-testid="email-send-confirm"
          disabled={!confirmOk || !canSend}
          onClick={() => void send()}
        >
          {sending ? "Sending…" : `Send to ${people(n)}`}
        </button>
      </div>
    </Dialog>
  );
}
