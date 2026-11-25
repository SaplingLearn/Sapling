"use client";
import React from "react";
import { AnimatePresence, motion } from "framer-motion";
import { BadgeArt } from "@/components/growth/BadgeArt";
import { Icon } from "@/components/Icon";
import { CustomSelect } from "@/components/CustomSelect";
import { AdminTableSkeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import { useConfirm } from "@/lib/useConfirm";
import { useMotionPresets } from "@/lib/motion";
import { AnimatedNumber } from "../AnimatedNumber";
import w from "./AchievementWiki.module.css";
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

const RARITIES: RarityTier[] = ["common", "uncommon", "rare", "epic", "legendary"];

/** The badge preview's size on a catalog card (BadgeArt's `size`, px). */
const CARD_BADGE_PX = 64;
/** The search field's icon (Icon's `size`, px). */
const SEARCH_ICON_PX = 14;

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
    <div className={w.root}>
      <div className={`body-serif ${w.summary}`}>
        <AnimatedNumber value={live.length} className={w.summaryLive} /> live · {" "}
        <span className={w.summaryDrafts}><AnimatedNumber value={drafts.length} /> work in progress</span>
      </div>

      <div className={`card ${w.filters}`}>
        <div className={w.search}>
          <div className={w.searchIcon}>
            <Icon name="search" size={SEARCH_ICON_PX} />
          </div>
          <input
            placeholder="Search name, slug, description…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            className={`${w.field} ${w.searchField}`}
          />
        </div>
        <CustomSelect
          ariaLabel="Category filter"
          size="sm"
          value={categoryFilter}
          onChange={setCategoryFilter}
          options={[{ value: "all" as const, label: "All categories" }, ...CAT_ORDER.map(c => ({ value: c, label: CAT_META[c].label }))]}
        />
        <CustomSelect
          ariaLabel="Rarity filter"
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
        <section className={w.section}>
          <div className={w.sectionHead}>
            <h2 className={w.sectionTitle}>Work in progress</h2>
            <span className="chip chip--warn"><AnimatedNumber value={drafts.length} /></span>
          </div>
          <div className={w.sectionNote}>
            Drafts are visible only here — users never see them and their triggers never fire.
          </div>
          {filteredDrafts.length === 0 ? (
            <div className={`label-micro ${w.empty}`}>No drafts match these filters.</div>
          ) : (
            <CardGrid items={filteredDrafts} onChange={patchLocal} />
          )}
        </section>
      )}

      <section className={w.section}>
        <div className={w.sectionHead}>
          <h2 className={w.sectionTitle}>Live catalog</h2>
          <span className="chip chip--accent"><AnimatedNumber value={live.length} /></span>
        </div>
        {filteredLive.length === 0 ? (
          <div className={`label-micro ${w.empty}`}>
            {live.length === 0 ? "No live achievements yet." : "No live achievements match these filters."}
          </div>
        ) : (
          <CardGrid items={filteredLive} onChange={patchLocal} />
        )}
      </section>

      <div className={w.panels}>
        <GrantPanel achievements={items} users={users} />
        <XpRulesPanel />
      </div>
    </div>
  );
}

/** A catalog section's cards. They arrive in a short stagger, and a card a
 *  filter brings back rises into its slot; one a filter drops simply leaves. */
function CardGrid({ items, onChange }: {
  items: Achievement[];
  onChange: (id: string, patch: Partial<Achievement>) => void;
}) {
  const m = useMotionPresets();
  return (
    <motion.div className={w.grid} variants={m.list.container} initial="hidden" animate="shown">
      {items.map(a => (
        <motion.div key={a.id} className={w.gridItem} variants={m.list.item}>
          <AchievementCard achievement={a} onChange={patch => onChange(a.id, patch)} />
        </motion.div>
      ))}
    </motion.div>
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
  const m = useMotionPresets();
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
    <div className={`card ${w.card}`}>
      <div className={w.cardTop}>
        <div className={w.cardArt}>
          <BadgeArt slug={achievement.slug} rarity={achievement.rarity} locked={false}
                    iconUrl={achievement.icon_url} emoji={achievement.icon} size={CARD_BADGE_PX} />
        </div>
        <div className={w.cardBody}>
          <div className={w.cardTitleRow}>
            <span className={w.cardName}>{achievement.name}</span>
            <span className={`chip ${w.tag}`}>{sentenceCase(achievement.rarity)}</span>
            <span className={`chip ${w.tag}`}>{CAT_META[achievement.category].label}</span>
            {achievement.is_secret && <span className="chip chip--warn">secret</span>}
          </div>
          <div className={w.cardDescription}>
            {achievement.description || <span className={w.dim}>No description yet.</span>}
          </div>
          <div className={w.cardMeta}>
            +{achievement.xp_reward} XP · sort {achievement.sort_order} · {achievement.slug}
          </div>
        </div>
      </div>

      <div className={w.cardActions}>
        <button className="btn btn--sm btn--ghost" onClick={toggleExpanded}>
          {expanded ? "Close" : "Edit"}
        </button>
        {isDraft ? (
          <button className="btn btn--sm btn--primary" onClick={publish} disabled={publishing}>
            {publishing ? "Publishing…" : "Publish"}
          </button>
        ) : (
          <button
            className={`btn btn--sm ${w.unpublish} ${unpublishConfirm.armed ? `btn--danger ${w.armed}` : "btn--ghost"}`}
            onClick={unpublishConfirm.trigger}
            disabled={publishing}
          >
            {publishing ? "…" : unpublishConfirm.armed ? "Click again to unpublish" : "Unpublish"}
          </button>
        )}
        {isDraft && (
          <span className={w.hint}>
            Grant is disabled until this is published.
          </span>
        )}
      </div>

      <AnimatePresence initial={false}>
      {expanded && (
        <motion.div key="editor" variants={{ hidden: m.collapse.initial, shown: m.collapse.animate, gone: m.collapse.exit }} initial="hidden" animate="shown" exit="gone" transition={m.collapse.transition}>
        <div className={w.editor}>
          <div className={w.editorFields}>
            <LabeledField label="Name">
              <input value={name} onChange={e => setName(e.target.value)} className={w.field} />
            </LabeledField>
            <LabeledField label="XP reward">
              <input type="number" value={xpReward} onChange={e => setXpReward(Number(e.target.value) || 0)} className={w.field} />
            </LabeledField>
            <LabeledField label="Category">
              <CustomSelect<AchievementCategory>
                ariaLabel="Category"
                value={category}
                onChange={setCategory}
                options={CAT_ORDER.map(c => ({ value: c, label: CAT_META[c].label }))}
              />
            </LabeledField>
            <LabeledField label="Rarity">
              <CustomSelect<RarityTier>
                ariaLabel="Rarity"
                value={rarity}
                onChange={setRarity}
                options={RARITIES.map(r => ({ value: r, label: r }))}
              />
            </LabeledField>
            <LabeledField label="Sort order">
              <input type="number" value={sortOrder} onChange={e => setSortOrder(Number(e.target.value) || 0)} className={w.field} />
            </LabeledField>
            <div className={w.secretCell}>
              <label className={w.checkLabel}>
                <input type="checkbox" checked={secret} onChange={e => setSecret(e.target.checked)} /> Secret (hidden until earned)
              </label>
            </div>
          </div>
          <LabeledField label="Description">
            <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2} className={w.field} />
          </LabeledField>
          <button className={`btn btn--primary btn--sm ${w.saveButton}`} onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </button>

          <div>
            <div className={`label-micro ${w.blockLabel}`}>Icon</div>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/webp,image/svg+xml"
              className={w.hiddenInput}
              onChange={e => handleFile(e.target.files?.[0])}
            />
            <div
              onClick={() => { if (!iconUploading) fileRef.current?.click(); }}
              onDragOver={e => e.preventDefault()}
              onDrop={e => { e.preventDefault(); if (!iconUploading) handleFile(e.dataTransfer.files?.[0]); }}
              className={`${w.dropzone} ${iconUploading ? w.dropzoneBusy : ""}`}
            >
              {iconUploading ? "Uploading…" : "Drop a 512×512 PNG, WebP or SVG here, or click to choose (≤512 KB)"}
            </div>
          </div>

          <div>
            <div className={`label-micro ${w.blockLabel}`}>Triggers · {triggers.length}</div>
            {triggers.length === 0 && <div className={w.none}>None.</div>}
            <AnimatePresence initial={false}>
            {triggers.map(t => (
              <motion.div key={t.id} className={w.row} variants={m.list.item} initial="hidden" animate="shown">
                <input
                  value={triggerDrafts[t.id]?.trigger_type ?? t.trigger_type}
                  onChange={e => setTriggerDrafts(prev => ({
                    ...prev, [t.id]: { ...prev[t.id], trigger_type: e.target.value },
                  }))}
                  onBlur={() => commitTrigger(t.id)}
                  onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
                  className={`${w.field} ${w.grow}`}
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
                  className={`${w.field} ${w.thresholdField}`}
                />
                <button className="btn btn--sm btn--ghost" onClick={() => deleteTriggerInline(t.id)}>×</button>
              </motion.div>
            ))}
            </AnimatePresence>
            <div className={w.addRow}>
              <input
                placeholder="trigger_type (e.g. login_streak)"
                value={newTrigger.trigger_type}
                onChange={e => setNewTrigger(v => ({ ...v, trigger_type: e.target.value }))}
                className={`${w.field} ${w.grow}`}
              />
              <input
                type="number"
                value={newTrigger.trigger_threshold}
                onChange={e => setNewTrigger(v => ({ ...v, trigger_threshold: Number(e.target.value) || 0 }))}
                className={`${w.field} ${w.thresholdField}`}
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
            <div className={`label-micro ${w.blockLabel}`}>Linked cosmetics · {linkedCosmeticIds.length}</div>
            {linkedCosmeticIds.length === 0 && <div className={w.none}>None.</div>}
            <AnimatePresence initial={false}>
            {linkedCosmeticIds.map(cid => {
              const c = cosmetics.find(x => x.id === cid);
              return (
                <motion.div key={cid} className={w.row} variants={m.list.item} initial="hidden" animate="shown">
                  <span className={`${w.field} ${w.grow} ${w.cosmeticName}`}>
                    <span>{c ? c.name : cid}</span>
                    {c && (
                      <span className={w.cosmeticMeta}>
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
                </motion.div>
              );
            })}
            </AnimatePresence>
            <div className={w.addRow}>
              <CustomSelect
                ariaLabel="Cosmetic to link"
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
        </motion.div>
      )}
      </AnimatePresence>
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
    <div className={`card ${w.grant}`}>
      <div className={`label-micro ${w.grantTitle}`}>Grant to user</div>
      <LabeledField label="User">
        <CustomSelect
          ariaLabel="User"
          size="sm"
          value={grant.userId}
          onChange={v => setGrant(g => ({ ...g, userId: v }))}
          options={users.map(u => ({ value: u.id, label: u.name || u.email, description: u.email }))}
          placeholder="Pick a user…"
        />
      </LabeledField>
      <LabeledField label="Achievement">
        <CustomSelect
          ariaLabel="Achievement"
          size="sm"
          value={grant.achievementId}
          onChange={v => setGrant(g => ({ ...g, achievementId: v }))}
          options={achievementOptions}
          placeholder="Pick one…"
        />
      </LabeledField>
      <div className={w.grantNote}>
        Drafts are disabled here — publish a badge first.
      </div>
      <button
        className={`btn ${w.grantButton}`}
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
  const m = useMotionPresets();
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
    <div className={`card ${w.rules}`}>
      <div className={w.rulesHead}>
        <div className="label-micro">XP rules · {rules.length}</div>
      </div>
      {rules.length === 0 && (
        <div className={w.rulesEmpty}>No XP rules defined.</div>
      )}
      <motion.div variants={m.list.container} initial="hidden" animate="shown">
      {rules.map(r => (
        <motion.div key={r.key} className={w.rule} variants={m.list.item}>
          <span className={w.ruleLabel}>{r.label}</span>
          <input
            type="number"
            value={drafts[r.key] ?? String(r.amount)}
            onChange={e => setDrafts(prev => ({ ...prev, [r.key]: e.target.value }))}
            onBlur={() => commitAmount(r.key)}
            onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
            disabled={busyKey === r.key}
            className={`${w.field} ${w.xpField}`}
          />
          <label className={w.checkLabel}>
            <input
              type="checkbox"
              checked={r.enabled}
              disabled={busyKey === r.key}
              onChange={e => toggleEnabled(r.key, e.target.checked)}
            /> Enabled
          </label>
        </motion.div>
      ))}
      </motion.div>
    </div>
  );
}

// ── Shared field helpers (mirrors Admin.tsx's private conventions) ──────────

function LabeledField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className={w.labeled}>
      <div className={`label-micro ${w.labeledLabel}`}>{label}</div>
      {children}
    </div>
  );
}
