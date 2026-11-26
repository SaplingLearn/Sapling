"use client";
import React from "react";

import Dialog from "@/components/Dialog";
import { Icon } from "@/components/Icon";
import { AdminTableSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import {
  adminApproveAllowlist,
  adminApproveAllowlistBulk,
  adminEmailStatus,
  adminListAllowlist,
  adminRevokeAllowlist,
} from "@/lib/api";
import type { AllowlistEmail, EmailStatus, InviteStatus } from "@/lib/types";

import { EmailNotConfiguredBanner } from "./EmailNotConfiguredBanner";
import { OpenAccessBanner } from "./OpenAccessBanner";
import { cn } from "@/lib/cn";

/**
 * Admin "Allowlist" tab: the waitlist, filterable by status, with per-row and
 * bulk approval. Approving sends the "you're in" email server-side; the
 * Invite column shows that email's delivery state. The banner on top is the
 * waitlist gate (`open_access`, docs/design/open-access-gate.md); a row whose
 * account came in through it is "open": in while the gate is open, waiting
 * while it is closed, and approvable either way. "Non-BU" is a label only.
 */

type RowStatus = "signup" | "open" | "approved" | "joined";
type Filter = "all" | RowStatus;

const FILTERS: { key: Filter; label: string }[] = [
  { key: "all", label: "All" },
  { key: "signup", label: "Signups" },
  { key: "open", label: "Open access" },
  { key: "approved", label: "Approved" },
  { key: "joined", label: "Joined" },
];

/** The backend's bulk endpoint takes 1..500 addresses per call. */
const BULK_LIMIT = 500;

export function rowStatus(row: AllowlistEmail): RowStatus {
  if (row.joined_at) return "joined";
  if (row.approved_at) return "approved";
  if (row.open_access) return "open";
  return "signup";
}

/** Not approved yet: a signup, or someone in (or waiting) through open access. */
const approvable = (row: AllowlistEmail) => !row.approved_at;

/** The status chip's text and style. An open-access row reads as "in" only
 *  while the gate is open, and "waiting" only while it is known to be closed:
 *  with the gate's state unread (null) it claims neither. */
function statusChip(st: RowStatus, gateOpen: boolean | null): { label: string; cls: string; title?: string } {
  if (st === "open") {
    if (gateOpen === null) {
      return { label: "open access", cls: "chip", title: "Joined through open access. Whether open access is on right now could not be read." };
    }
    return gateOpen
      ? { label: "open access", cls: "chip--info", title: "Using Sapling through open access. Approve to keep them in when you require the waitlist again." }
      : { label: "waiting", cls: "chip--warn", title: "Joined during open access; back on the waitlist now that it is required." };
  }
  return { label: st, cls: st === "signup" ? "chip--warn" : "chip--accent" };
}

const INVITE_CHIP: Record<InviteStatus, { cls: string; title: string }> = {
  sent: { cls: "chip chip--accent", title: "The “you’re in” email was sent." },
  failed: { cls: "chip chip--warn", title: "Sending the “you’re in” email failed." },
  queued: { cls: "chip", title: "Queued to send." },
  skipped: { cls: "chip", title: "Not sent: Resend not configured." },
  suppressed: { cls: "chip", title: "Not sent: this address unsubscribed." },
};

function InviteChip({ status, email }: { status: InviteStatus | null | undefined; email: string }) {
  if (!status) return <span className="text-text-muted">—</span>;
  const meta = INVITE_CHIP[status] ?? { cls: "chip", title: status };
  return (
    <span className={meta.cls} title={meta.title} data-testid={`allowlist-invite-${email}`}>
      {status}
    </span>
  );
}

/** Toast for a single approval, driven by the invite status the server returned. */
function approvalToast(
  toast: ReturnType<typeof useToast>,
  row: AllowlistEmail | undefined,
  email: string,
  status: EmailStatus | null,
) {
  const s = row?.invite_status ?? (status && !status.configured ? "skipped" : null);
  switch (s) {
    case "sent":
      toast.success(`Approved ${email}. "You're in" email sent.`);
      return;
    case "queued":
      toast.success(`Approved ${email}. "You're in" email queued.`);
      return;
    case "skipped":
      toast.success(`Approved ${email}. No email sent: Resend isn't configured.`);
      return;
    case "suppressed":
      toast.success(`Approved ${email}. No email sent: they unsubscribed.`);
      return;
    case "failed":
      toast.warn(`Approved ${email}, but the "you're in" email failed to send.`);
      return;
    default:
      toast.success(`Approved ${email}.`);
  }
}

function fmtDate(iso: string | null | undefined) {
  return iso ? new Date(iso).toLocaleDateString() : "—";
}

export function AllowlistTab() {
  const toast = useToast();
  const [emails, setEmails] = React.useState<AllowlistEmail[]>([]);
  const [query, setQuery] = React.useState("");
  const [filter, setFilter] = React.useState<Filter>("all");
  const [nonBuOnly, setNonBuOnly] = React.useState(false);
  // null until the banner has read the gate (and if that read fails).
  const [gateOpen, setGateOpen] = React.useState<boolean | null>(null);
  const [selected, setSelected] = React.useState<Set<string>>(() => new Set());
  const [newEmail, setNewEmail] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [emailStatus, setEmailStatus] = React.useState<EmailStatus | null>(null);
  const [confirmOpen, setConfirmOpen] = React.useState(false);
  const [bulkBusy, setBulkBusy] = React.useState(false);
  const headerBoxRef = React.useRef<HTMLInputElement | null>(null);

  const load = React.useCallback(async () => {
    try {
      const r = await adminListAllowlist();
      setEmails(r.emails || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => { void load(); }, [load]);

  React.useEffect(() => {
    // A failed status read leaves the banner hidden rather than crying wolf.
    adminEmailStatus().then(setEmailStatus, () => setEmailStatus(null));
  }, []);

  const counts = React.useMemo(() => {
    const c: Record<Filter, number> = { all: emails.length, signup: 0, open: 0, approved: 0, joined: 0 };
    for (const e of emails) c[rowStatus(e)] += 1;
    return c;
  }, [emails]);

  const q = query.trim().toLowerCase();
  const nonBuCount = emails.filter((e) => e.school_email === false).length;
  const filtered = emails.filter(
    (e) => (filter === "all" || rowStatus(e) === filter)
      && (!nonBuOnly || e.school_email === false)
      && (!q || e.email.toLowerCase().includes(q)),
  );

  // Selection only ever holds unapproved rows; derive it from the live list so
  // a row approved elsewhere (or by a reload) silently drops out.
  const selectedRows = emails.filter((e) => approvable(e) && selected.has(e.email));
  const selectableVisible = filtered.filter(approvable);
  const visibleSelectedCount = selectableVisible.filter((e) => selected.has(e.email)).length;
  const allVisibleSelected = selectableVisible.length > 0 && visibleSelectedCount === selectableVisible.length;
  const someVisibleSelected = visibleSelectedCount > 0 && !allVisibleSelected;

  React.useEffect(() => {
    if (headerBoxRef.current) headerBoxRef.current.indeterminate = someVisibleSelected;
  }, [someVisibleSelected]);

  const toggleRow = (email: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(email)) next.delete(email);
      else next.add(email);
      return next;
    });
  };

  const toggleAllVisible = () => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (allVisibleSelected) selectableVisible.forEach((e) => next.delete(e.email));
      else selectableVisible.forEach((e) => next.add(e.email));
      return next;
    });
  };

  const add = async () => {
    const e = newEmail.trim().toLowerCase();
    if (!e) return;
    setBusy(true);
    try {
      const r = await adminApproveAllowlist(e);
      setNewEmail("");
      approvalToast(toast, r?.email, e, emailStatus);
      await load();
    } catch (err) {
      toast.error(`Add failed: ${String(err)}`);
    } finally {
      setBusy(false);
    }
  };

  const toggle = async (row: AllowlistEmail) => {
    try {
      if (row.approved_at) {
        await adminRevokeAllowlist(row.email);
        toast.success("Allowlist revoked");
      } else {
        const r = await adminApproveAllowlist(row.email);
        approvalToast(toast, r?.email, row.email, emailStatus);
      }
      await load();
    } catch (err) {
      toast.error(`Update failed: ${String(err)}`);
    }
  };

  const approveSelected = async () => {
    const targets = selectedRows.map((e) => e.email);
    if (targets.length === 0) return;
    setBulkBusy(true);
    let approved = 0;
    let done = 0;
    try {
      for (let i = 0; i < targets.length; i += BULK_LIMIT) {
        const batch = targets.slice(i, i + BULK_LIMIT);
        const r = await adminApproveAllowlistBulk(batch);
        approved += r?.approved ?? 0;
        done += batch.length;
      }
      const tail = emailStatus && !emailStatus.configured
        ? " No emails sent: Resend isn't configured."
        : ` "You're in" email${approved === 1 ? "" : "s"} on the way.`;
      toast.success(`Approved ${approved} of ${targets.length}.${tail}`);
      setSelected(new Set());
      setConfirmOpen(false);
    } catch (err) {
      const partial = done > 0 ? ` (${approved} approved before the failure)` : "";
      toast.error(`Bulk approve failed${partial}: ${String(err)}`);
    } finally {
      setBulkBusy(false);
      await load();
    }
  };

  if (loading) return <AdminTableSkeleton />;

  const notConfigured = emailStatus !== null && !emailStatus.configured;
  const n = selectedRows.length;

  return (
    <>
      <OpenAccessBanner onChanged={setGateOpen} />
      {notConfigured && <EmailNotConfiguredBanner />}
      <div className="body-serif text-[15px] mb-5.5 text-text-dim max-w-170">
        <span className="text-text">{emails.length}</span> address{emails.length === 1 ? "" : "es"} · {" "}
        <span className="text-accent">{emails.filter((e) => e.approved_at).length} approved</span> · {counts.joined} joined
        {counts.signup > 0 && <> · <span className="text-warn">{counts.signup} unapproved signups</span></>}
        {counts.open > 0 && <> · {counts.open} {gateOpen === null ? "joined through open access" : gateOpen ? "in through open access" : "waiting after open access"}</>}
      </div>
      <div className="card p-0">
        <div className="flex flex-wrap py-3 px-4 border-b border-b-border items-center gap-3">
          <div className="relative flex-1 min-w-45 max-w-75">
            <div className="absolute left-2.5 top-2 text-text-muted">
              <Icon name="search" size={14} />
            </div>
            <input
              data-testid="allowlist-search"
              placeholder="Search emails…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              className="w-full pt-[7px] pr-3 pb-[7px] pl-8 border border-border rounded-sm text-md bg-bg-input"
            />
          </div>
          <input
            data-testid="allowlist-add-input"
            placeholder="someone@example.com"
            value={newEmail}
            onChange={(e) => setNewEmail(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") void add(); }}
            className="w-full py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] max-w-60"
          />
          <button
            type="button"
            data-testid="allowlist-add"
            className="btn btn--primary btn--sm"
            onClick={() => void add()}
            disabled={busy || !newEmail.trim()}
          >
            {busy ? "Adding…" : "Allowlist"}
          </button>
        </div>
        <div className="flex flex-wrap py-2.5 px-4 border-b border-b-border items-center gap-1.5">
          {FILTERS.map((f) => (
            <button
              key={f.key}
              type="button"
              data-testid={`allowlist-filter-${f.key}`}
              aria-pressed={filter === f.key}
              className={cn(`chip ${filter === f.key ? "chip--accent" : ""}`, "cursor-pointer", filter === f.key ? "" : "border border-dashed border-border")}
              onClick={() => setFilter(f.key)}
            >
              {f.label} ({counts[f.key]})
            </button>
          ))}
          <button
            type="button"
            data-testid="allowlist-filter-non-bu"
            aria-pressed={nonBuOnly}
            className={cn(`chip ${nonBuOnly ? "chip--accent" : ""}`, "cursor-pointer", nonBuOnly ? "" : "border border-dashed border-border")}
            onClick={() => setNonBuOnly((v) => !v)}
          >
            Non-BU ({nonBuCount})
          </button>
          <div className="flex-1" />
          <button
            type="button"
            data-testid="allowlist-bulk-approve"
            className="btn btn--primary btn--sm"
            disabled={n === 0 || bulkBusy}
            onClick={() => setConfirmOpen(true)}
          >
            Approve selected ({n})
          </button>
        </div>
        <table className="w-full border-collapse text-md">
          <thead>
            <tr className="bg-bg-subtle">
              <th className="text-left py-2.5 px-4 font-medium text-md text-text-muted w-9 pr-0">
                <input
                  ref={headerBoxRef}
                  type="checkbox"
                  data-testid="allowlist-select-all"
                  aria-label="Select all unapproved addresses shown"
                  checked={allVisibleSelected}
                  disabled={selectableVisible.length === 0}
                  onChange={toggleAllVisible}
                />
              </th>
              {["Email", "Status", "Invite", "Submitted", "Approved", "Joined", ""].map((h) => (
                <th key={h} className="text-left py-2.5 px-4 font-medium text-md text-text-muted">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 && (
              <tr>
                <td colSpan={8} className="p-7 text-center text-text-muted">
                  No addresses match.
                </td>
              </tr>
            )}
            {filtered.map((row) => {
              const st = rowStatus(row);
              const chip = statusChip(st, gateOpen);
              return (
                <tr key={row.id} data-testid={`allowlist-row-${row.email}`} className="border-t border-t-border">
                  <td className="py-2.5 px-4 pr-0">
                    {approvable(row) && (
                      <input
                        type="checkbox"
                        data-testid={`allowlist-select-${row.email}`}
                        aria-label={`Select ${row.email}`}
                        checked={selected.has(row.email)}
                        onChange={() => toggleRow(row.email)}
                      />
                    )}
                  </td>
                  <td className="py-2.5 px-4 font-medium">
                    {row.email}
                    {row.school_email === false && (
                      <span
                        className="chip ml-2"
                        data-testid={`allowlist-non-bu-${row.email}`}
                        title="Not a BU address. A label only: it decides nothing."
                      >
                        Non-BU
                      </span>
                    )}
                  </td>
                  <td className="py-2.5 px-4">
                    <span
                      className={`chip ${chip.cls}`}
                      title={chip.title}
                      data-testid={`allowlist-status-${row.email}`}
                    >
                      {chip.label}
                    </span>
                  </td>
                  <td className="py-2.5 px-4">
                    <InviteChip status={row.invite_status} email={row.email} />
                  </td>
                  <td className="py-2.5 px-4 text-text-muted">{fmtDate(row.created_at)}</td>
                  <td className="py-2.5 px-4 text-text-muted">{fmtDate(row.approved_at)}</td>
                  <td className="py-2.5 px-4 text-text-muted">{fmtDate(row.joined_at)}</td>
                  <td className="py-2.5 px-4 text-right">
                    <button
                      type="button"
                      data-testid={`allowlist-toggle-${row.email}`}
                      className={`btn btn--sm ${row.approved_at ? "btn--ghost" : "btn--primary"}`}
                      onClick={() => void toggle(row)}
                    >
                      {row.approved_at ? "Revoke" : "Approve"}
                    </button>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <Dialog
        open={confirmOpen}
        onClose={() => { if (!bulkBusy) setConfirmOpen(false); }}
        size="sm"
        title={`Approve ${n} ${n === 1 ? "person" : "people"}?`}
      >
        <p className="flags__confirm-text mb-3" data-testid="allowlist-bulk-confirm-text">
          {notConfigured
            ? "The approvals will be saved, but no emails go out until Resend is configured."
            : gateOpen !== false && selectedRows.some((e) => e.open_access)
              ? gateOpen
                ? "Each gets a “you’re in” email, except anyone who joined through open access: they already use Sapling."
                : "Each gets a “you’re in” email, except anyone who joined through open access while it is on."
              : `Each gets a “you’re in” email.`}
        </p>
        <ul
          className="mt-0 mx-0 mb-5 py-2 px-3 list-none max-h-40 overflow-y-auto border border-border rounded-sm text-sm text-text-dim"
        >
          {selectedRows.map((e) => <li key={e.id}>{e.email}</li>)}
        </ul>
        <div className="flags__confirm-actions">
          <button
            type="button"
            className="btn"
            data-testid="allowlist-bulk-cancel"
            disabled={bulkBusy}
            onClick={() => setConfirmOpen(false)}
          >
            Cancel
          </button>
          <button
            type="button"
            className="btn btn--primary"
            data-testid="allowlist-bulk-confirm"
            disabled={bulkBusy || n === 0}
            onClick={() => void approveSelected()}
          >
            {bulkBusy ? "Approving…" : `Approve ${n}`}
          </button>
        </div>
      </Dialog>
    </>
  );
}
