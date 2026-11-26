"use client";
import React from "react";
import { BadgeArt } from "@/components/growth/BadgeArt";
import { Icon } from "@/components/Icon";
import { CustomSelect } from "@/components/CustomSelect";
import { AdminTableSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { CAT_META, CAT_ORDER } from "../achievements/BadgeGrid";
import {
  adminListAchievements, adminUpdateAchievement, adminUploadAchievementIcon,
  adminListXpRules, adminUpdateXpRule, adminGrantAchievement,
  adminListTriggers, adminCreateTrigger, adminUpdateTrigger, adminDeleteTrigger,
  adminListAchievementCosmetics, adminLinkAchievementCosmetic, adminUnlinkAchievementCosmetic,
  adminListCosmetics,
  adminFetchUsers,
} from "@/lib/api";
import type {
  Achievement, AchievementCategory, RarityTier, AchievementTrigger, Cosmetic,
  AdminUserListItem as AdminUser,
} from "@/lib/types";
import { sentenceCase } from "@/lib/sentenceCase";
import { cn } from "@/lib/cn";
import { fieldClass } from "@/components/ui/field";

const RARITIES: RarityTier[] = ["common", "uncommon", "rare", "epic", "legendary"];

// ── Icon validation (client-side convenience only — the server enforces the
// same rules and is the real gate). Specific messages beat "invalid image". ─
const ICON_PX = 512;
const MAX_ICON_BYTES = 512 * 1024;

export async function readIcon(file: File): Promise<{ base64: string; contentType: string }> {
  if (!["image/png", "image/webp", "image/svg+xml"].includes(file.type)) {
    throw new Error("Icon must be a PNG, WebP or SVG");
  }
  if (file.size > MAX_ICON_BYTES) {
    throw new Error(`Icon must be 512 KB or smaller (this one is ${Math.round(file.size / 1024)} KB)`);
  }
  if (file.type !== "image/svg+xml") {
    const bitmap = await createImageBitmap(file);
    const { width, height } = bitmap;
    bitmap.close();
    if (width !== ICON_PX || height !== ICON_PX) {
      throw new Error(`Icon must be exactly ${ICON_PX}×${ICON_PX} (this one is ${width}×${height})`);
    }
  }
  const buffer = await file.arrayBuffer();
  const bytes = new Uint8Array(buffer);
  let binary = "";
  for (let i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return { base64: btoa(binary), contentType: file.type };
}

// ── Root ─────────────────────────────────────────────────────────────────────

export function AchievementWiki() {
  const toast = useToast();
  const [items, setItems] = React.useState<Achievement[]>([]);
  const [users, setUsers] = React.useState<AdminUser[]>([]);
  const [loading, setLoading] = React.useState(true);

  const [categoryFilter, setCategoryFilter] = React.useState<"all" | AchievementCategory>("all");
  const [rarityFilter, setRarityFilter] = React.useState<"all" | RarityTier>("all");
  const [search, setSearch] = React.useState("");

  const load = React.useCallback(async () => {
    setLoading(true);
    try {
      const [a, u] = await Promise.all([adminListAchievements(), adminFetchUsers()]);
      setItems(a.achievements || []);
      setUsers(u.users || []);
    } catch (err) {
      toast.error(`Load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => { load(); }, [load]);

  // A card patches its own fields on success; this folds that patch into the
  // shared list so the header counts, other panels, and the grant dropdown
  // all stay in sync without a refetch.
  const patchLocal = React.useCallback((id: string, patch: Partial<Achievement>) => {
    setItems(prev => prev.map(a => (a.id === id ? { ...a, ...patch } : a)));
  }, []);

  const matches = React.useCallback((a: Achievement) => {
    if (categoryFilter !== "all" && a.category !== categoryFilter) return false;
    if (rarityFilter !== "all" && a.rarity !== rarityFilter) return false;
    const q = search.trim().toLowerCase();
    if (q) {
      const hay = `${a.name} ${a.slug} ${a.description || ""}`.toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  }, [categoryFilter, rarityFilter, search]);

  const drafts = React.useMemo(() => items.filter(a => a.status === "draft"), [items]);
  const live = React.useMemo(
    () => items.filter(a => a.status === "live")
      .sort((a, b) => a.sort_order - b.sort_order || a.name.localeCompare(b.name)),
    [items],
  );
  const filteredDrafts = React.useMemo(() => drafts.filter(matches), [drafts, matches]);
  const filteredLive = React.useMemo(() => live.filter(matches), [live, matches]);

  const filtersActive = categoryFilter !== "all" || rarityFilter !== "all" || search.trim() !== "";

  if (loading && items.length === 0) {
    return <AdminTableSkeleton />;
  }

  return (
    <div>
      <div className="body-serif text-[15px] mb-4.5 text-text-dim max-w-195">
        <span className="text-text">{live.length}</span> live · {" "}
        <span className="text-text-muted">{drafts.length} work in progress</span>
      </div>

      <div className="card py-3 px-4 mb-6 flex gap-3 flex-wrap items-center">
        <div className="relative flex-1 min-w-50 max-w-80">
          <div className="absolute left-2.5 top-2 text-text-muted">
            <Icon name="search" size={14} />
          </div>
          <input
            placeholder="Search name, slug, description…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="w-full pt-[7px] pr-3 pb-[7px] pl-8 border border-border rounded-sm text-md bg-bg-input"
          />
        </div>
        <CustomSelect
          size="sm"
          value={categoryFilter}
          onChange={setCategoryFilter}
          options={[{ value: "all" as const, label: "All categories" }, ...CAT_ORDER.map(c => ({ value: c, label: CAT_META[c].label }))]}
        />
        <CustomSelect
          size="sm"
          value={rarityFilter}
          onChange={setRarityFilter}
          options={[{ value: "all" as const, label: "All rarities" }, ...RARITIES.map(r => ({ value: r, label: r }))]}
        />
        {filtersActive && (
          <button
            className="btn btn--sm btn--ghost"
            onClick={() => { setCategoryFilter("all"); setRarityFilter("all"); setSearch(""); }}
          >
            Clear filters
          </button>
        )}
      </div>

      {drafts.length > 0 && (
        <section className="mb-9">
          <div className="flex items-baseline gap-2.5 mb-1.5">
            <h2 className="m-0 text-[20px] font-semibold">Work in progress</h2>
            <span className="chip chip--warn">{drafts.length}</span>
          </div>
          <div className="text-[12.5px] text-text-muted mb-4 max-w-160">
            Drafts are visible only here — users never see them and their triggers never fire.
          </div>
          {filteredDrafts.length === 0 ? (
            <div className="label-micro py-2 px-0">No drafts match these filters.</div>
          ) : (
            <div className="grid grid-cols-[repeat(auto-fill,_minmax(340px,_1fr))] gap-3.5">
              {filteredDrafts.map(a => (
                <AchievementCard key={a.id} achievement={a} onChange={patch => patchLocal(a.id, patch)} />
              ))}
            </div>
          )}
        </section>
      )}

      <section className="mb-9">
        <div className="flex items-baseline gap-2.5 mb-1.5">
          <h2 className="m-0 text-[20px] font-semibold">Live catalog</h2>
          <span className="chip chip--accent">{live.length}</span>
        </div>
        {filteredLive.length === 0 ? (
          <div className="label-micro py-2 px-0">
            {live.length === 0 ? "No live achievements yet." : "No live achievements match these filters."}
          </div>
        ) : (
          <div className="grid grid-cols-[repeat(auto-fill,_minmax(340px,_1fr))] gap-3.5">
            {filteredLive.map(a => (
              <AchievementCard key={a.id} achievement={a} onChange={patch => patchLocal(a.id, patch)} />
            ))}
          </div>
        )}
      </section>

      <div className="grid grid-cols-[minmax(260px,_340px)_1fr] gap-5 [align-items:start]">
        <GrantPanel achievements={items} users={users} />
        <XpRulesPanel />
      </div>
    </div>
  );
}

// ── Achievement card: preview, publish/unpublish, inline edit, icon,
//    triggers. Fully self-contained so any number of cards can be expanded
//    at once without the parent tracking a single "open" id. ────────────────

function AchievementCard({
  achievement, onChange,
}: {
  achievement: Achievement;
  onChange: (patch: Partial<Achievement>) => void;
}) {
  const toast = useToast();
  const isDraft = achievement.status === "draft";
  const [expanded, setExpanded] = React.useState(false);

  const [name, setName] = React.useState(achievement.name);
  const [description, setDescription] = React.useState(achievement.description || "");
  const [category, setCategory] = React.useState<AchievementCategory>(achievement.category);
  const [rarity, setRarity] = React.useState<RarityTier>(achievement.rarity);
  const [xpReward, setXpReward] = React.useState(achievement.xp_reward);
  const [sortOrder, setSortOrder] = React.useState(achievement.sort_order);
  const [secret, setSecret] = React.useState(achievement.is_secret);
  const [saving, setSaving] = React.useState(false);

  const [publishing, setPublishing] = React.useState(false);
  const [iconUploading, setIconUploading] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  const [triggers, setTriggers] = React.useState<AchievementTrigger[]>([]);
  const [newTrigger, setNewTrigger] = React.useState({ trigger_type: "", trigger_threshold: 1 });
  // Uncommitted per-trigger edits, keyed by trigger id. Present only while a
  // field is being typed in; commitTrigger clears the entry on blur so the
  // inputs fall back to the server's value.
  const [triggerDrafts, setTriggerDrafts] = React.useState<
    Record<string, { trigger_type?: string; trigger_threshold?: number }>
  >({});
  const [addingTrigger, setAddingTrigger] = React.useState(false);

  const [cosmetics, setCosmetics] = React.useState<Cosmetic[]>([]);
  const [linkedCosmeticIds, setLinkedCosmeticIds] = React.useState<string[]>([]);
  const [pendingCosmeticId, setPendingCosmeticId] = React.useState("");
  const [cosmeticBusyId, setCosmeticBusyId] = React.useState<string | null>(null);

  // Deliberately depends on the whole `achievement` object (not just its id):
  // the id never changes for a card's lifetime, so a narrower dep array would
  // freeze this closure on the achievement's first-render values forever and
  // silently repopulate the form with stale data on every re-expand.
  const resetEditFields = React.useCallback(() => {
    setName(achievement.name);
    setDescription(achievement.description || "");
    setCategory(achievement.category);
    setRarity(achievement.rarity);
    setXpReward(achievement.xp_reward);
    setSortOrder(achievement.sort_order);
    setSecret(achievement.is_secret);
  }, [achievement]);

  const toggleExpanded = () => {
    if (!expanded) resetEditFields();
    setExpanded(e => !e);
  };

  React.useEffect(() => {
    if (!expanded) return;
    let alive = true;
    Promise.all([
      adminListTriggers(achievement.id),
      adminListAchievementCosmetics(achievement.id),
      adminListCosmetics(),
    ])
      .then(([t, links, c]) => {
        if (!alive) return;
        setTriggers(t.triggers || []);
        setLinkedCosmeticIds((links.links || []).map(l => l.cosmetic_id));
        setCosmetics(c.cosmetics || []);
      })
      .catch(err => { if (alive) toast.error(`Detail load failed: ${String(err)}`); });
    return () => { alive = false; };
  }, [expanded, achievement.id, toast]);

  const reloadTriggers = React.useCallback(async () => {
    try {
      const r = await adminListTriggers(achievement.id);
      setTriggers(r.triggers || []);
    } catch (err) {
      toast.error(`Trigger load failed: ${String(err)}`);
    }
  }, [achievement.id, toast]);

  const reloadCosmeticLinks = React.useCallback(async () => {
    try {
      const r = await adminListAchievementCosmetics(achievement.id);
      setLinkedCosmeticIds((r.links || []).map(l => l.cosmetic_id));
    } catch (err) {
      toast.error(`Cosmetic link load failed: ${String(err)}`);
    }
  }, [achievement.id, toast]);

  const save = async () => {
    if (!name.trim()) { toast.warn("Name is required."); return; }
    const patch: Partial<Achievement> = {};
    if (name.trim() !== achievement.name) patch.name = name.trim();
    const trimmedDesc = description.trim() || null;
    if (trimmedDesc !== (achievement.description ?? null)) patch.description = trimmedDesc;
    if (category !== achievement.category) patch.category = category;
    if (rarity !== achievement.rarity) patch.rarity = rarity;
    if (xpReward !== achievement.xp_reward) patch.xp_reward = xpReward;
    if (sortOrder !== achievement.sort_order) patch.sort_order = sortOrder;
    if (secret !== achievement.is_secret) patch.is_secret = secret;

    if (Object.keys(patch).length === 0) {
      setExpanded(false);
      return;
    }

    setSaving(true);
    try {
      await adminUpdateAchievement(achievement.id, patch);
      onChange(patch);
      toast.success("Saved");
    } catch (err) {
      // The optimistic edit never touched shared state — the card keeps
      // showing what the admin typed so they can retry, but the catalog
      // (and every other view reading `items`) still shows the truth.
      toast.error(`Save failed: ${String(err)}`);
    } finally {
      setSaving(false);
    }
  };

  const publish = async () => {
    setPublishing(true);
    try {
      await adminUpdateAchievement(achievement.id, { status: "live" });
      onChange({ status: "live" });
      toast.success(`${achievement.name} published`);
    } catch (err) {
      toast.error(`Publish failed: ${String(err)}`);
    } finally {
      setPublishing(false);
    }
  };

  const unpublish = async () => {
    setPublishing(true);
    try {
      await adminUpdateAchievement(achievement.id, { status: "draft" });
      onChange({ status: "draft" });
      toast.success(`${achievement.name} unpublished`);
    } catch (err) {
      toast.error(`Unpublish failed: ${String(err)}`);
    } finally {
      setPublishing(false);
    }
  };
  const unpublishConfirm = useConfirm(unpublish);

  const handleFile = async (file: File | null | undefined) => {
    if (!file || iconUploading) return;
    setIconUploading(true);
    try {
      const { base64, contentType } = await readIcon(file);
      const res = await adminUploadAchievementIcon(achievement.id, base64, contentType);
      onChange({ icon_url: res.icon_url });
      toast.success("Icon uploaded");
    } catch (err) {
      toast.error(err instanceof Error ? err.message : `Icon upload failed: ${String(err)}`);
    } finally {
      setIconUploading(false);
      if (fileRef.current) fileRef.current.value = "";
    }
  };

  const addTrigger = async () => {
    if (addingTrigger) return;   // a double-click would create two triggers
    if (!newTrigger.trigger_type.trim()) { toast.warn("Trigger type required."); return; }
    setAddingTrigger(true);
    try {
      await adminCreateTrigger({
        achievement_id: achievement.id,
        trigger_type: newTrigger.trigger_type.trim(),
        trigger_threshold: newTrigger.trigger_threshold,
      });
      setNewTrigger({ trigger_type: "", trigger_threshold: 1 });
      await reloadTriggers();
      toast.success("Trigger added");
    } catch (err) { toast.error(`Add failed: ${String(err)}`); }
    finally { setAddingTrigger(false); }
  };

  // Commit a trigger edit on blur, never on keystroke.
  //
  // These inputs used to PATCH straight from onChange, so typing a 12-char
  // trigger_type fired 12 writes and 12 full reloadTriggers() calls — and
  // because reloadTriggers replaces `triggers` (and therefore each input's
  // `value`), a response for an early keystroke landing after a later one
  // rewrote the field mid-typing and characters vanished. Same draft/onBlur
  // shape XpRulesPanel already uses below.
  const commitTrigger = async (tid: string) => {
    const draft = triggerDrafts[tid];
    if (!draft) return;
    setTriggerDrafts(prev => { const next = { ...prev }; delete next[tid]; return next; });

    const current = triggers.find(t => t.id === tid);
    if (!current) return;
    const patch: { trigger_type?: string; trigger_threshold?: number } = {};
    if (draft.trigger_type !== undefined && draft.trigger_type !== current.trigger_type) {
      if (!draft.trigger_type.trim()) { toast.warn("Trigger type required."); return; }
      patch.trigger_type = draft.trigger_type.trim();
    }
    if (draft.trigger_threshold !== undefined && draft.trigger_threshold !== current.trigger_threshold) {
      patch.trigger_threshold = draft.trigger_threshold;
    }
    if (!Object.keys(patch).length) return;   // blurred without changing anything

    try {
      await adminUpdateTrigger(tid, patch);
      await reloadTriggers();
    } catch (err) { toast.error(`Update failed: ${String(err)}`); }
  };

  const deleteTriggerInline = async (tid: string) => {
    try {
      await adminDeleteTrigger(tid);
      await reloadTriggers();
      toast.success("Trigger deleted");
    } catch (err) { toast.error(`Delete failed: ${String(err)}`); }
  };

  const linkCosmetic = async (cosmeticId: string) => {
    setCosmeticBusyId(cosmeticId);
    try {
      await adminLinkAchievementCosmetic(achievement.id, cosmeticId);
      setPendingCosmeticId("");
      await reloadCosmeticLinks();
      toast.success("Cosmetic linked");
    } catch (err) {
      toast.error(`Link failed: ${String(err)}`);
    } finally {
      setCosmeticBusyId(null);
    }
  };

  const unlinkCosmetic = async (cosmeticId: string) => {
    setCosmeticBusyId(cosmeticId);
    try {
      await adminUnlinkAchievementCosmetic(achievement.id, cosmeticId);
      await reloadCosmeticLinks();
      toast.success("Cosmetic unlinked");
    } catch (err) {
      toast.error(`Unlink failed: ${String(err)}`);
    } finally {
      setCosmeticBusyId(null);
    }
  };

  return (
    <div className="card p-4">
      <div className="flex gap-3.5 items-start">
        <div className="shrink-0">
          <BadgeArt slug={achievement.slug} rarity={achievement.rarity} locked={false}
                    iconUrl={achievement.icon_url} emoji={achievement.icon} size={64} />
        </div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="font-semibold text-[14.5px]">{achievement.name}</span>
            <span className="chip text-sm">{sentenceCase(achievement.rarity)}</span>
            <span className="chip text-sm">{CAT_META[achievement.category].label}</span>
            {achievement.is_secret && <span className="chip chip--warn">secret</span>}
          </div>
          <div className="text-sm text-text-dim mt-[5px] leading-[1.45]">
            {achievement.description || <span className="text-text-muted">No description yet.</span>}
          </div>
          <div className="text-xs text-text-muted mt-1.5">
            +{achievement.xp_reward} XP · sort {achievement.sort_order} · {achievement.slug}
          </div>
        </div>
      </div>

      <div className="flex gap-2 mt-3 flex-wrap items-center">
        <button className="btn btn--sm btn--ghost" onClick={toggleExpanded}>
          {expanded ? "Close" : "Edit"}
        </button>
        {isDraft ? (
          <button className="btn btn--sm btn--primary" onClick={publish} disabled={publishing}>
            {publishing ? "Publishing…" : "Publish"}
          </button>
        ) : (
          <button
            className={`btn btn--sm ${unpublishConfirm.armed ? "btn--danger" : "btn--ghost"}`}
            onClick={unpublishConfirm.trigger}
            disabled={publishing}
            style={unpublishConfirm.armed ? { background: "var(--err-soft)", color: "var(--err)" } : undefined}
          >
            {publishing ? "…" : unpublishConfirm.armed ? "Click again to unpublish" : "Unpublish"}
          </button>
        )}
        {isDraft && (
          <span className="text-xs text-text-muted">
            Grant is disabled until this is published.
          </span>
        )}
      </div>

      {expanded && (
        <div className="mt-4 pt-4 [border-top:1px_dashed_var(--border)] grid gap-4">
          <div className="grid grid-cols-[1fr_1fr] gap-3">
            <LabeledField label="Name">
              <input value={name} onChange={e => setName(e.target.value)} className={fieldClass} />
            </LabeledField>
            <LabeledField label="XP reward">
              <input type="number" value={xpReward} onChange={e => setXpReward(Number(e.target.value) || 0)} className={fieldClass} />
            </LabeledField>
            <LabeledField label="Category">
              <CustomSelect<AchievementCategory>
                value={category}
                onChange={setCategory}
                options={CAT_ORDER.map(c => ({ value: c, label: CAT_META[c].label }))}
              />
            </LabeledField>
            <LabeledField label="Rarity">
              <CustomSelect<RarityTier>
                value={rarity}
                onChange={setRarity}
                options={RARITIES.map(r => ({ value: r, label: r }))}
              />
            </LabeledField>
            <LabeledField label="Sort order">
              <input type="number" value={sortOrder} onChange={e => setSortOrder(Number(e.target.value) || 0)} className={fieldClass} />
            </LabeledField>
            <div className="flex items-end pb-2">
              <label className="inline-flex items-center gap-1.5 text-sm text-text-dim">
                <input type="checkbox" checked={secret} onChange={e => setSecret(e.target.checked)} /> Secret (hidden until earned)
              </label>
            </div>
          </div>
          <LabeledField label="Description">
            <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2} className={fieldClass} />
          </LabeledField>
          <button className="btn btn--primary btn--sm [justify-self:start]" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>

          <div>
            <div className="label-micro mb-1.5">Icon</div>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/webp,image/svg+xml"
              className="hidden"
              onChange={e => handleFile(e.target.files?.[0])}
            />
            <div
              onClick={() => { if (!iconUploading) fileRef.current?.click(); }}
              onDragOver={e => e.preventDefault()}
              onDrop={e => { e.preventDefault(); if (!iconUploading) handleFile(e.dataTransfer.files?.[0]); }}
              className={cn("border border-dashed border-border rounded-md p-3.5 text-center text-sm text-text-muted", iconUploading ? "cursor-default" : "cursor-pointer", iconUploading ? "opacity-70" : "opacity-100")}
            >
              {iconUploading ? "Uploading…" : "Drop a 512×512 PNG, WebP or SVG here, or click to choose (≤512 KB)"}
            </div>
          </div>

          <div>
            <div className="label-micro mb-1.5">Triggers · {triggers.length}</div>
            {triggers.length === 0 && <div className="text-sm text-text-muted">None.</div>}
            {triggers.map(t => (
              <div key={t.id} className="flex gap-1.5 items-center mb-1.5">
                <input
                  value={triggerDrafts[t.id]?.trigger_type ?? t.trigger_type}
                  onChange={e => setTriggerDrafts(prev => ({
                    ...prev, [t.id]: { ...prev[t.id], trigger_type: e.target.value },
                  }))}
                  onBlur={() => commitTrigger(t.id)}
                  onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                  className="w-full py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] flex-1"
                />
                <input
                  type="number"
                  value={triggerDrafts[t.id]?.trigger_threshold ?? t.trigger_threshold}
                  onChange={e => setTriggerDrafts(prev => ({
                    ...prev,
                    [t.id]: { ...prev[t.id], trigger_threshold: Number(e.target.value) || 0 },
                  }))}
                  onBlur={() => commitTrigger(t.id)}
                  onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                  className="py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] w-20"
                />
                <button className="btn btn--sm btn--ghost" onClick={() => deleteTriggerInline(t.id)}>×</button>
              </div>
            ))}
            <div className="flex gap-1.5 items-center mt-1.5">
              <input
                placeholder="trigger_type (e.g. login_streak)"
                value={newTrigger.trigger_type}
                onChange={e => setNewTrigger(v => ({ ...v, trigger_type: e.target.value }))}
                className="w-full py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] flex-1"
              />
              <input
                type="number"
                value={newTrigger.trigger_threshold}
                onChange={e => setNewTrigger(v => ({ ...v, trigger_threshold: Number(e.target.value) || 0 }))}
                className="py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] w-20"
              />
              <button
                className="btn btn--sm btn--primary"
                onClick={addTrigger}
                disabled={addingTrigger}
              >
                {addingTrigger ? "Adding…" : "Add"}
              </button>
            </div>
          </div>

          <div>
            <div className="label-micro mb-1.5">Linked cosmetics · {linkedCosmeticIds.length}</div>
            {linkedCosmeticIds.length === 0 && <div className="text-sm text-text-muted">None.</div>}
            {linkedCosmeticIds.map(cid => {
              const c = cosmetics.find(x => x.id === cid);
              return (
                <div key={cid} className="flex gap-1.5 items-center mb-1.5">
                  <span className="w-full py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] flex-1 flex items-center gap-2">
                    <span>{c ? c.name : cid}</span>
                    {c && (
                      <span className="text-sm text-text-muted">
                        {sentenceCase(c.type)} · {sentenceCase(c.rarity)}
                      </span>
                    )}
                  </span>
                  <button
                    className="btn btn--sm btn--ghost"
                    onClick={() => unlinkCosmetic(cid)}
                    disabled={cosmeticBusyId === cid}
                  >
                    ×
                  </button>
                </div>
              );
            })}
            <div className="flex gap-1.5 items-center mt-1.5">
              <CustomSelect
                size="sm"
                value={pendingCosmeticId}
                onChange={setPendingCosmeticId}
                options={cosmetics
                  .filter(c => !linkedCosmeticIds.includes(c.id))
                  .map(c => ({ value: c.id, label: c.name, description: `${sentenceCase(c.type)} · ${sentenceCase(c.rarity)}` }))}
                placeholder={cosmetics.length === 0 ? "No cosmetics defined yet" : "Pick a cosmetic to link…"}
                disabled={cosmetics.filter(c => !linkedCosmeticIds.includes(c.id)).length === 0}
              />
              <button
                className="btn btn--sm btn--primary"
                onClick={() => linkCosmetic(pendingCosmeticId)}
                disabled={!pendingCosmeticId || cosmeticBusyId === pendingCosmeticId}
              >
                Link
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

// ── Grant to user ────────────────────────────────────────────────────────────

function GrantPanel({ achievements, users }: { achievements: Achievement[]; users: AdminUser[] }) {
  const toast = useToast();
  const [grant, setGrant] = React.useState<{ userId: string; achievementId: string }>({ userId: "", achievementId: "" });
  const [granting, setGranting] = React.useState(false);

  const achievementOptions = React.useMemo(
    () => achievements
      .slice()
      .sort((a, b) => a.name.localeCompare(b.name))
      .map(a => ({
        value: a.id,
        label: a.name,
        description: a.status === "draft" ? "Draft — publish to grant" : a.rarity,
        disabled: a.status === "draft",
      })),
    [achievements],
  );

  const doGrant = async () => {
    if (!grant.userId || !grant.achievementId) {
      toast.warn("Pick a user and an achievement.");
      return;
    }
    setGranting(true);
    try {
      await adminGrantAchievement(grant.userId, grant.achievementId);
      toast.success("Achievement granted");
      setGrant({ userId: "", achievementId: "" });
    } catch (err) {
      toast.error(`Grant failed: ${String(err)}`);
    } finally {
      setGranting(false);
    }
  };

  return (
    <div className="card p-(--pad-lg)">
      <div className="label-micro mb-2.5">Grant to user</div>
      <LabeledField label="User">
        <CustomSelect
          size="sm"
          value={grant.userId}
          onChange={v => setGrant(g => ({ ...g, userId: v }))}
          options={users.map(u => ({ value: u.id, label: u.name || u.email, description: u.email }))}
          placeholder="Pick a user…"
        />
      </LabeledField>
      <LabeledField label="Achievement">
        <CustomSelect
          size="sm"
          value={grant.achievementId}
          onChange={v => setGrant(g => ({ ...g, achievementId: v }))}
          options={achievementOptions}
          placeholder="Pick one…"
        />
      </LabeledField>
      <div className="text-xs text-text-muted -mt-1 mb-2.5">
        Drafts are disabled here — publish a badge first.
      </div>
      <button
        className="btn w-full"
        onClick={doGrant}
        disabled={granting || !grant.userId || !grant.achievementId}
      >
        {granting ? "Granting…" : "Grant achievement"}
      </button>
    </div>
  );
}

// ── XP rules ─────────────────────────────────────────────────────────────────

interface XpRule { key: string; label: string; amount: number; enabled: boolean }

function XpRulesPanel() {
  const toast = useToast();
  const [rules, setRules] = React.useState<XpRule[]>([]);
  const [loading, setLoading] = React.useState(true);
  const [busyKey, setBusyKey] = React.useState<string | null>(null);
  const [drafts, setDrafts] = React.useState<Record<string, string>>({});

  const load = React.useCallback(async () => {
    try {
      const r = await adminListXpRules();
      setRules(r.rules || []);
    } catch (err) {
      toast.error(`XP rules load failed: ${String(err)}`);
    } finally {
      setLoading(false);
    }
  }, [toast]);

  React.useEffect(() => { load(); }, [load]);

  const commitAmount = async (key: string) => {
    const raw = drafts[key];
    if (raw === undefined) return;
    const amount = Number(raw);
    const rule = rules.find(r => r.key === key);
    setDrafts(prev => { const next = { ...prev }; delete next[key]; return next; });
    if (!rule || !Number.isFinite(amount) || amount === rule.amount) return;
    setBusyKey(key);
    try {
      await adminUpdateXpRule(key, { amount });
      setRules(prev => prev.map(r => (r.key === key ? { ...r, amount } : r)));
      toast.success("XP rule updated");
    } catch (err) {
      toast.error(`Update failed: ${String(err)}`);
    } finally {
      setBusyKey(null);
    }
  };

  const toggleEnabled = async (key: string, enabled: boolean) => {
    setBusyKey(key);
    try {
      await adminUpdateXpRule(key, { enabled });
      setRules(prev => prev.map(r => (r.key === key ? { ...r, enabled } : r)));
      toast.success("XP rule updated");
    } catch (err) {
      toast.error(`Update failed: ${String(err)}`);
    } finally {
      setBusyKey(null);
    }
  };

  if (loading) return <AdminTableSkeleton />;

  return (
    <div className="card p-0">
      <div className="py-3 px-4 border-b border-b-border">
        <div className="label-micro">XP rules · {rules.length}</div>
      </div>
      {rules.length === 0 && (
        <div className="p-7 text-center text-text-muted text-md">No XP rules defined.</div>
      )}
      {rules.map(r => (
        <div key={r.key} className="flex items-center gap-3 py-2.5 px-4 border-t border-t-border text-md">
          <span className="flex-1 font-medium">{r.label}</span>
          <input
            type="number"
            value={drafts[r.key] ?? String(r.amount)}
            onChange={e => setDrafts(prev => ({ ...prev, [r.key]: e.target.value }))}
            onBlur={() => commitAmount(r.key)}
            onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
            disabled={busyKey === r.key}
            className="py-[7px] px-2.5 border border-border rounded-sm text-md bg-bg-input [font-family:inherit] w-22.5"
          />
          <label className="inline-flex items-center gap-1.5 text-sm text-text-dim">
            <input
              type="checkbox"
              checked={r.enabled}
              disabled={busyKey === r.key}
              onChange={e => toggleEnabled(r.key, e.target.checked)}
            /> Enabled
          </label>
        </div>
      ))}
    </div>
  );
}

// ── Shared field helpers (mirrors Admin.tsx's private conventions) ──────────

function LabeledField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="mb-2.5">
      <div className="label-micro mb-1">{label}</div>
      {children}
    </div>
  );
}

