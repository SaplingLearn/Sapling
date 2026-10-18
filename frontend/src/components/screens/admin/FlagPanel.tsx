"use client";
import React from "react";

import { Icon } from "@/components/Icon";
import { useToast } from "@/components/ToastProvider";
import { Sheet } from "@/components/ui/Sheet";
import { Toggle } from "@/components/ui/Toggle";
import { InfoTip, Tooltip } from "@/components/ui/Tooltip";
import {
  adminDeleteFlagTarget, adminExplainFlag, adminFetchUsers, adminUpdateFlag, adminUpsertFlagTarget,
  type AdminFlag,
} from "@/lib/api";
import type { AdminUserListItem } from "@/lib/types";

import { changeSummary, explainPhrase, flagMeta, otherVariant, variantLabel } from "./flagLabels";

const PRESETS = [0, 10, 25, 50, 100];

/**
 * The right-hand panel for one flag: everyone default + gradual rollout
 * (staged, saved together from the sticky footer, which states the scope
 * first), role/student overrides (saved immediately), and a per-student
 * check. `flag === null` means closed.
 */
export function FlagPanel({ flag, roles, onClose, onSaved }: {
  flag: AdminFlag | null;
  roles: { id: string; name: string }[];
  onClose: () => void;
  onSaved: (f: AdminFlag) => void;
}) {
  return (
    <Sheet
      open={flag !== null}
      onClose={onClose}
      title={flag ? flagMeta(flag.key).title : ""}
      width={520}
      testid={flag ? `flag-panel-${flag.key}` : undefined}
    >
      {flag && <PanelBody key={flag.key} flag={flag} roles={roles} onSaved={onSaved} />}
    </Sheet>
  );
}

function PanelBody({ flag, roles, onSaved }: {
  flag: AdminFlag; roles: { id: string; name: string }[]; onSaved: (f: AdminFlag) => void;
}) {
  const toast = useToast();
  const { hideFlag } = flagMeta(flag.key);
  const [def, setDef] = React.useState(flag.default_variant);
  const [pct, setPct] = React.useState(flag.rollout_percent);
  const [rv, setRv] = React.useState<string | null>(flag.rollout_variant);
  const [saving, setSaving] = React.useState(false);

  // Server state moved under us (a save here, or the row switch): re-seed.
  React.useEffect(() => {
    setDef(flag.default_variant);
    setPct(flag.rollout_percent);
    setRv(flag.rollout_variant);
  }, [flag.default_variant, flag.rollout_percent, flag.rollout_variant]);

  // The rollout serves "the other variant" whenever there is only one; a
  // chosen variant that now equals the default is cleared, not saved.
  const implied = otherVariant(flag, def);
  const rolloutVariant = implied ?? (rv !== def ? rv : null);
  const next = { def, pct, rv: pct > 0 ? rolloutVariant : null };
  const summary = changeSummary(flag, next);
  const invalid = pct > 0 && !rolloutVariant;

  const discard = () => {
    setDef(flag.default_variant);
    setPct(flag.rollout_percent);
    setRv(flag.rollout_variant);
  };

  const save = async () => {
    setSaving(true);
    try {
      const r = await adminUpdateFlag(flag.key, {
        default_variant: def, rollout_percent: pct, rollout_variant: next.rv,
      });
      onSaved(r.flag);
      toast.success("Flag saved");
    } catch (err) {
      toast.error(`Couldn't save: ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const variantOptions = flag.variants.map((v) => ({ value: v, label: variantLabel(flag, v) }));

  return (
    <div className="flag-panel">
      <p className="flag-panel__desc">{flag.description}</p>

      <section className="flag-panel__section">
        <SectionHead
          title="Everyone"
          tip="What every student gets unless a rollout or an override says otherwise."
        />
        <div className="flag-panel__fit">
          <Toggle options={variantOptions} value={def} onChange={setDef} testid={`flag-default-${flag.key}`} />
        </div>
      </section>

      <section className="flag-panel__section">
        <SectionHead
          title="Gradual rollout"
          tip="Gives a share of students the other setting. Each student lands in a fixed bucket, so raising the percentage only adds students; nobody flips back and forth."
        />
        <div className="flag-panel__rollout-line">
          {implied ? (
            <span>
              Make it <strong>{variantLabel(flag, implied)}</strong> for
            </span>
          ) : (
            <>
              <span>Serve</span>
              <Toggle
                size="sm"
                options={variantOptions.filter((o) => o.value !== def)}
                value={rolloutVariant ?? ""}
                onChange={(v) => setRv(v)}
                testid={`flag-rollout-variant-${flag.key}`}
              />
              <span>to</span>
            </>
          )}
          <strong className="flag-panel__pct" data-testid={`flag-rollout-value-${flag.key}`}>{pct}%</strong>
          <span>of students</span>
        </div>
        <div className="flag-panel__presets" role="group" aria-label="Rollout presets">
          {PRESETS.map((p) => (
            <button
              key={p}
              type="button"
              className="flag-panel__preset"
              aria-pressed={pct === p}
              data-testid={`flag-rollout-preset-${flag.key}-${p}`}
              onClick={() => setPct(p)}
            >
              {p === 0 ? "Off" : `${p}%`}
            </button>
          ))}
        </div>
        <input
          type="range"
          min={0}
          max={100}
          step={1}
          value={pct}
          aria-label="Rollout percentage"
          className="flag-panel__range"
          data-testid={`flag-rollout-${flag.key}`}
          onChange={(e) => setPct(Number(e.target.value))}
        />
      </section>

      <Overrides flag={flag} roles={roles} onSaved={onSaved} hideFlag={hideFlag} />

      <CheckStudent flag={flag} roles={roles} />

      {(summary || invalid) && (
        <div className="flag-panel__footer">
          <p className="flag-panel__summary" data-testid={`flag-save-scope-${flag.key}`}>
            {invalid ? "Pick which setting the rollout serves." : summary}
          </p>
          <div className="flag-panel__footer-actions">
            <button type="button" className="btn btn--ghost" data-testid={`flag-discard-${flag.key}`} onClick={discard}>
              Discard
            </button>
            <button
              type="button"
              className="btn btn--primary"
              data-testid={`flag-save-${flag.key}`}
              disabled={saving || invalid}
              onClick={() => void save()}
            >
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

function SectionHead({ title, tip, children }: { title: string; tip: string; children?: React.ReactNode }) {
  return (
    <div className="flag-panel__section-head">
      <h3 className="flag-panel__section-title">{title}</h3>
      <InfoTip content={tip} label={`About ${title.toLowerCase()}`} />
      {children}
    </div>
  );
}

/** Debounced student lookup over the admin user search. */
function useStudentSearch() {
  const [query, setQuery] = React.useState("");
  const [hits, setHits] = React.useState<AdminUserListItem[]>([]);
  React.useEffect(() => {
    const q = query.trim();
    if (q.length < 2) { setHits([]); return; }
    let live = true;
    const t = setTimeout(() => {
      adminFetchUsers({ q, page_size: 6 }).then(
        (r) => { if (live) setHits(r.users); },
        () => { if (live) setHits([]); },
      );
    }, 200);
    return () => { live = false; clearTimeout(t); };
  }, [query]);
  return { query, setQuery, hits, clear: () => { setQuery(""); setHits([]); } };
}

const userLabel = (u: AdminUserListItem) => u.name || u.email || u.id;

function StudentResults({ hits, testidPrefix, onPick }: {
  hits: AdminUserListItem[]; testidPrefix: string; onPick: (u: AdminUserListItem) => void;
}) {
  if (hits.length === 0) return null;
  return (
    <ul className="flag-panel__results" role="listbox">
      {hits.map((u) => (
        <li key={u.id} role="option" aria-selected={false}>
          <button type="button" data-testid={`${testidPrefix}-${u.id}`} onClick={() => onPick(u)}>
            <span>{userLabel(u)}</span>
            {u.email && u.name && <span className="flag-panel__result-sub">{u.email}</span>}
          </button>
        </li>
      ))}
    </ul>
  );
}

function Overrides({ flag, roles, onSaved, hideFlag }: {
  flag: AdminFlag; roles: { id: string; name: string }[]; onSaved: (f: AdminFlag) => void; hideFlag: boolean;
}) {
  const toast = useToast();
  const [type, setType] = React.useState<"role" | "user">("role");
  const [targetId, setTargetId] = React.useState("");
  const [picked, setPicked] = React.useState<string>("");
  const [variant, setVariant] = React.useState(flag.variants[flag.variants.length - 1] ?? flag.variants[0]);
  const search = useStudentSearch();

  const reset = () => { setTargetId(""); setPicked(""); search.clear(); };

  const add = async () => {
    if (!targetId) return;
    try {
      const r = await adminUpsertFlagTarget(flag.key, { target_type: type, target_id: targetId, variant });
      onSaved(r.flag);
      reset();
      toast.success("Override added");
    } catch (err) {
      toast.error(`Couldn't add override: ${String(err)}`);
    }
  };

  const remove = async (t: "user" | "role", id: string) => {
    try {
      onSaved((await adminDeleteFlagTarget(flag.key, t, id)).flag);
    } catch (err) {
      toast.error(`Couldn't remove override: ${String(err)}`);
    }
  };

  return (
    <section className="flag-panel__section">
      <div className="flag-panel__section-head">
        <h3 className="flag-panel__section-title">Overrides</h3>
        <InfoTip
          label="About overrides"
          content="Pin a role or one student to a setting. Overrides beat the rollout and the everyone default; a student's own override beats their role's. Saved as soon as you add or remove one."
        />
      </div>

      {flag.targets.length === 0 ? (
        <p className="flag-panel__muted">No overrides. Everyone follows the settings above.</p>
      ) : (
        <ul className="flag-panel__overrides">
          {flag.targets.map((t) => (
            <li key={`${t.target_type}-${t.target_id}`} data-testid={`flag-target-row-${flag.key}-${t.target_type}-${t.target_id}`}>
              <span className="chip">{t.target_type === "role" ? "Role" : "Student"}</span>
              <span className="flag-panel__override-label">{t.label}</span>
              <span className={`chip ${hideFlag && t.variant === "on" ? "chip--warn" : "chip--accent"}`}>
                {variantLabel(flag, t.variant)}
              </span>
              <Tooltip content={`Remove this override; ${t.label} goes back to the settings above`}>
                <button
                  type="button"
                  className="btn btn--ghost btn--sm flag-panel__remove"
                  aria-label={`Remove override for ${t.label}`}
                  data-testid={`flag-target-remove-${flag.key}-${t.target_type}-${t.target_id}`}
                  onClick={() => void remove(t.target_type, t.target_id)}
                >
                  <Icon name="x" size={14} />
                </button>
              </Tooltip>
            </li>
          ))}
        </ul>
      )}

      <div className="flag-panel__add">
        <div className="flag-panel__add-row">
          <div className="flag-panel__fit">
            <Toggle
              size="sm"
              options={[{ value: "role", label: "Role" }, { value: "user", label: "Student" }]}
              value={type}
              onChange={(v) => { setType(v); reset(); }}
              testid={`flag-target-type-${flag.key}`}
            />
          </div>
          {type === "role" ? (
            <select
              className="field"
              aria-label="Role"
              data-testid={`flag-target-role-${flag.key}`}
              value={targetId}
              onChange={(e) => setTargetId(e.target.value)}
            >
              <option value="">Pick a role…</option>
              {roles.map((r) => <option key={r.id} value={r.id}>{r.name}</option>)}
            </select>
          ) : (
            <input
              className="field"
              aria-label="Search students"
              placeholder="Search students by name or email…"
              data-testid={`flag-target-user-search-${flag.key}`}
              value={picked || search.query}
              onChange={(e) => { setPicked(""); setTargetId(""); search.setQuery(e.target.value); }}
            />
          )}
        </div>
        {type === "user" && !picked && (
          <StudentResults
            hits={search.hits}
            testidPrefix={`flag-target-user-result-${flag.key}`}
            onPick={(u) => { setTargetId(u.id); setPicked(userLabel(u)); search.clear(); }}
          />
        )}
        <div className="flag-panel__add-row">
          <span className="flag-panel__muted">Set to</span>
          <div className="flag-panel__fit">
            <Toggle
              size="sm"
              options={flag.variants.map((v) => ({ value: v, label: variantLabel(flag, v) }))}
              value={variant}
              onChange={setVariant}
              testid={`flag-target-variant-${flag.key}`}
            />
          </div>
          <button
            type="button"
            className="btn btn--sm flag-panel__add-btn"
            data-testid={`flag-target-add-${flag.key}`}
            disabled={!targetId}
            onClick={() => void add()}
          >
            Add override
          </button>
        </div>
      </div>
    </section>
  );
}

function CheckStudent({ flag, roles }: { flag: AdminFlag; roles: { id: string; name: string }[] }) {
  const toast = useToast();
  const search = useStudentSearch();
  const [result, setResult] = React.useState<{ who: string; text: string } | null>(null);

  const check = async (id: string, who: string) => {
    if (!id.trim()) return;
    try {
      const r = await adminExplainFlag(flag.key, id.trim());
      setResult({ who, text: explainPhrase(flag, r, (rid) => roles.find((x) => x.id === rid)?.name) });
      search.clear();
    } catch (err) {
      toast.error(`Couldn't check that student: ${String(err)}`);
    }
  };

  return (
    <section className="flag-panel__section">
      <div className="flag-panel__section-head">
        <h3 className="flag-panel__section-title">Check a student</h3>
        <InfoTip
          label="About checking a student"
          content="See exactly what one student gets right now, and which rule decided it. Search by name or email, or paste a user id and press Enter."
        />
      </div>
      <input
        className="field"
        aria-label="Check a student"
        placeholder="Name, email or user id…"
        data-testid={`flag-explain-input-${flag.key}`}
        value={search.query}
        onChange={(e) => search.setQuery(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") void check(search.query, search.query.trim()); }}
      />
      <StudentResults
        hits={search.hits}
        testidPrefix={`flag-explain-user-${flag.key}`}
        onPick={(u) => void check(u.id, userLabel(u))}
      />
      {result && (
        <div className="flag-panel__explain" data-testid={`flag-explain-result-${flag.key}`}>
          <span className="flag-panel__muted">{result.who}</span>
          <span>{result.text}</span>
        </div>
      )}
    </section>
  );
}
