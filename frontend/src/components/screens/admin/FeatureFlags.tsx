"use client";
import React from "react";

import Dialog from "@/components/Dialog";
import { Icon } from "@/components/Icon";
import { AdminTableSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import { Switch } from "@/components/ui/Switch";
import { InfoTip, Tooltip } from "@/components/ui/Tooltip";
import { adminListFlags, adminListRoles, adminUpdateFlag, type AdminFlag } from "@/lib/api";

import { FlagPanel } from "./FlagPanel";
import { changeSummary, flagMeta, groupFlags, relativeTime, rolloutPhrase, switchFor, variantLabel } from "./flagLabels";

/**
 * Admin "Feature flags" tab (#620, ADR 0029).
 *
 * The list is grouped like the nav. Each row carries a switch for the
 * everyone-default (confirmed in a dialog that states the scope, spec §7);
 * everything else — gradual rollout, role/student overrides, "what would
 * student X see" — lives in a right-hand panel opened from the row.
 */
export function FeatureFlagsTab() {
  const toast = useToast();
  const [flags, setFlags] = React.useState<AdminFlag[] | null>(null);
  const [roles, setRoles] = React.useState<{ id: string; name: string }[]>([]);
  const [openKey, setOpenKey] = React.useState<string | null>(null);
  const [pending, setPending] = React.useState<{ flag: AdminFlag; next: string } | null>(null);

  React.useEffect(() => {
    adminListFlags().then(
      (r) => setFlags(r.flags),
      (err) => { setFlags([]); toast.error(`Couldn't load flags: ${String(err)}`); },
    );
    adminListRoles().then((r) => setRoles(r.roles), () => setRoles([]));
  }, [toast]);

  const replace = React.useCallback(
    (f: AdminFlag) => setFlags((all) => (all ?? []).map((x) => (x.key === f.key ? f : x))),
    [],
  );

  if (!flags) return <AdminTableSkeleton />;

  const openFlag = flags.find((f) => f.key === openKey) ?? null;

  return (
    <div className="flags">
      <div className="flags__intro">
        <p>
          Hide a feature from the nav for everyone, roll it out to a share of students, or override it for a
          role or a single student.
        </p>
        <InfoTip
          label="How flags resolve"
          content={
            <>
              <strong>Who wins, in order:</strong> a student&apos;s own override, then a role override, then the
              gradual rollout, then the everyone default. Saved changes reach every server within 30 seconds.
            </>
          }
        />
      </div>

      {flags.length === 0 && (
        <div className="card flags__empty">No flags defined.</div>
      )}

      {groupFlags(flags).map(({ group, flags: inGroup }) => (
        <section key={group} className="flags__group" aria-labelledby={`flags-group-${group}`}>
          <h3 id={`flags-group-${group}`} className="label-micro flags__group-title">{group}</h3>
          <div className="card flags__list">
            {inGroup.map((f) => (
              <FlagRow
                key={f.key}
                flag={f}
                onOpen={() => setOpenKey(f.key)}
                onToggle={(next) => setPending({ flag: f, next })}
              />
            ))}
          </div>
        </section>
      ))}

      <FlagPanel
        flag={openFlag}
        roles={roles}
        onClose={() => setOpenKey(null)}
        onSaved={replace}
      />

      <ConfirmDefault
        pending={pending}
        onCancel={() => setPending(null)}
        onSaved={(f) => { replace(f); setPending(null); }}
      />
    </div>
  );
}

function FlagRow({ flag, onOpen, onToggle }: {
  flag: AdminFlag; onOpen: () => void; onToggle: (nextVariant: string) => void;
}) {
  const { title, hideFlag } = flagMeta(flag.key);
  const sw = switchFor(flag);
  const rollout = rolloutPhrase(flag, flag.rollout_percent, flag.rollout_variant);
  const overrides = flag.targets.length;

  return (
    <div className="flag-row" data-testid={`flag-row-${flag.key}`} onClick={onOpen}>
      <div className="flag-row__main">
        <div className="flag-row__title">{title}</div>
        <div className="flag-row__desc">{flag.description}</div>
      </div>

      <div className="flag-row__chips">
        {rollout && (
          <Tooltip content={`Rolling out: ${rollout}. The rest get the everyone default.`}>
            <span className="chip chip--warn" tabIndex={0}>{flag.rollout_percent}% rollout</span>
          </Tooltip>
        )}
        {overrides > 0 && (
          <Tooltip
            content={flag.targets
              .map((t) => `${t.target_type === "role" ? "Role" : "Student"} ${t.label}: ${variantLabel(flag, t.variant)}`)
              .join(" · ")}
          >
            <span className="chip chip--info" tabIndex={0}>
              {overrides} override{overrides === 1 ? "" : "s"}
            </span>
          </Tooltip>
        )}
      </div>

      <div className="flag-row__changed">
        {flag.updated_at ? (
          <Tooltip
            content={`Changed by ${flag.updated_by_name ?? flag.updated_by ?? "unknown"} on ${new Date(flag.updated_at).toLocaleString()}`}
          >
            <span tabIndex={0}>{relativeTime(flag.updated_at)}</span>
          </Tooltip>
        ) : (
          <Tooltip content="Never changed: running on its built-in default.">
            <span tabIndex={0}>Never changed</span>
          </Tooltip>
        )}
      </div>

      <div className="flag-row__state" onClick={(e) => e.stopPropagation()}>
        <span className="flag-row__state-label" data-testid={`flag-state-${flag.key}`}>
          {variantLabel(flag, flag.default_variant)}
        </span>
        {sw && (
          <Tooltip
            content={hideFlag
              ? `${sw.checked ? "Hide" : "Show"} ${title} for everyone without an override`
              : `Turn ${title} ${sw.checked ? "off" : "on"} for everyone without an override`}
          >
            <Switch
              checked={sw.checked}
              label={hideFlag ? `${title} visible to everyone` : `${title} on for everyone`}
              testid={`flag-toggle-${flag.key}`}
              onChange={(c) => onToggle(sw.variantWhen(c))}
            />
          </Tooltip>
        )}
      </div>

      <Tooltip content="Rollout, overrides and student check">
        <button
          type="button"
          className="flag-row__open btn btn--ghost btn--sm"
          aria-label={`Configure ${title}`}
          data-testid={`flag-open-${flag.key}`}
          onClick={(e) => { e.stopPropagation(); onOpen(); }}
        >
          <Icon name="chev" size={14} />
        </button>
      </Tooltip>
    </div>
  );
}

/** The row switch's confirm step: states who the change reaches (spec §7). */
function ConfirmDefault({ pending, onCancel, onSaved }: {
  pending: { flag: AdminFlag; next: string } | null;
  onCancel: () => void;
  onSaved: (f: AdminFlag) => void;
}) {
  const toast = useToast();
  const [saving, setSaving] = React.useState(false);
  if (!pending) return null;
  const { flag, next } = pending;
  const { title } = flagMeta(flag.key);
  // A rollout that would now serve the new default means nothing; end it.
  const endsRollout = flag.rollout_percent > 0 && flag.rollout_variant === next;
  const body = endsRollout
    ? { default_variant: next, rollout_percent: 0, rollout_variant: null }
    : { default_variant: next };
  const summary = changeSummary(flag, {
    def: next,
    pct: endsRollout ? 0 : flag.rollout_percent,
    rv: endsRollout ? null : flag.rollout_variant,
  });

  const confirm = async () => {
    setSaving(true);
    try {
      const r = await adminUpdateFlag(flag.key, body);
      onSaved(r.flag);
      toast.success(`${title}: ${variantLabel(flag, next)} for everyone`);
    } catch (err) {
      toast.error(`Couldn't save: ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open onClose={onCancel} size="sm" title={`Make ${title} ${variantLabel(flag, next).toLowerCase()}?`}>
      <p className="flags__confirm-text" data-testid={`flag-save-scope-${flag.key}`}>{summary}</p>
      <div className="flags__confirm-actions">
        <button type="button" className="btn" data-testid={`flag-cancel-${flag.key}`} onClick={onCancel}>Cancel</button>
        <button
          type="button"
          className="btn btn--primary"
          data-testid={`flag-confirm-${flag.key}`}
          disabled={saving}
          onClick={() => void confirm()}
        >
          {saving ? "Saving…" : `Make ${variantLabel(flag, next).toLowerCase()}`}
        </button>
      </div>
    </Dialog>
  );
}
