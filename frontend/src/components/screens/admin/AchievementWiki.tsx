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
      <div className="body-serif" style={{ fontSize: 15, marginBottom: 18, color: "var(--text-dim)", maxWidth: 780 }}>
        <span style={{ color: "var(--text)" }}>{live.length}</span> live · {" "}
        <span style={{ color: "var(--text-muted)" }}>{drafts.length} work in progress</span>
      </div>

      <div className="card" style={{ padding: "12px 16px", marginBottom: 24, display: "flex", gap: 12, flexWrap: "wrap", alignItems: "center" }}>
        <div style={{ position: "relative", flex: 1, minWidth: 200, maxWidth: 320 }}>
          <div style={{ position: "absolute", left: 10, top: 8, color: "var(--text-muted)" }}>
            <Icon name="search" size={14} />
          </div>
          <input
            placeholder="Search name, slug, description…"
            value={search}
            onChange={e => setSearch(e.target.value)}
            style={{
              width: "100%", padding: "7px 12px 7px 32px",
              border: "1px solid var(--border)", borderRadius: "var(--r-sm)",
              fontSize: 13, background: "var(--bg-input)",
            }}
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
        <section style={{ marginBottom: 36 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 6 }}>
            <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>Work in progress</h2>
            <span className="chip chip--warn">{drafts.length}</span>
          </div>
          <div style={{ fontSize: 12.5, color: "var(--text-muted)", marginBottom: 16, maxWidth: 640 }}>
            Drafts are visible only here — users never see them and their triggers never fire.
          </div>
          {filteredDrafts.length === 0 ? (
            <div className="label-micro" style={{ padding: "8px 0" }}>No drafts match these filters.</div>
          ) : (
            <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 14 }}>
              {filteredDrafts.map(a => (
                <AchievementCard key={a.id} achievement={a} onChange={patch => patchLocal(a.id, patch)} />
              ))}
            </div>
          )}
        </section>
      )}

      <section style={{ marginBottom: 36 }}>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10, marginBottom: 6 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>Live catalog</h2>
          <span className="chip chip--accent">{live.length}</span>
        </div>
        {filteredLive.length === 0 ? (
          <div className="label-micro" style={{ padding: "8px 0" }}>
            {live.length === 0 ? "No live achievements yet." : "No live achievements match these filters."}
          </div>
        ) : (
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(340px, 1fr))", gap: 14 }}>
            {filteredLive.map(a => (
              <AchievementCard key={a.id} achievement={a} onChange={patch => patchLocal(a.id, patch)} />
            ))}
          </div>
        )}
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "minmax(260px, 340px) 1fr", gap: 20, alignItems: "start" }}>
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
    if (!newTrigger.trigger_type.trim()) { toast.warn("Trigger type required."); return; }
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
  };

  const updateTriggerInline = async (tid: string, patch: Partial<AchievementTrigger>) => {
    try {
      await adminUpdateTrigger(tid, {
        ...(patch.trigger_type !== undefined ? { trigger_type: patch.trigger_type } : {}),
        ...(patch.trigger_threshold !== undefined ? { trigger_threshold: patch.trigger_threshold } : {}),
      });
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
    <div className="card" style={{ padding: 16 }}>
      <div style={{ display: "flex", gap: 14, alignItems: "flex-start" }}>
        <div style={{ flexShrink: 0 }}>
          <BadgeArt slug={achievement.slug} rarity={achievement.rarity} locked={false}
                    iconUrl={achievement.icon_url} emoji={achievement.icon} size={64} />
        </div>
        <div style={{ flex: 1, minWidth: 0 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
            <span style={{ fontWeight: 600, fontSize: 14.5 }}>{achievement.name}</span>
            <span className="chip" style={{ textTransform: "uppercase", fontSize: 10 }}>{achievement.rarity}</span>
            <span className="chip" style={{ fontSize: 10 }}>{CAT_META[achievement.category].label}</span>
            {achievement.is_secret && <span className="chip chip--warn">secret</span>}
          </div>
          <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 5, lineHeight: 1.45 }}>
            {achievement.description || <span style={{ color: "var(--text-muted)" }}>No description yet.</span>}
          </div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: 6 }}>
            +{achievement.xp_reward} XP · sort {achievement.sort_order} · {achievement.slug}
          </div>
        </div>
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap", alignItems: "center" }}>
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
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            Grant is disabled until this is published.
          </span>
        )}
      </div>

      {expanded && (
        <div style={{ marginTop: 16, paddingTop: 16, borderTop: "1px dashed var(--border)", display: "grid", gap: 16 }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
            <LabeledField label="Name">
              <input value={name} onChange={e => setName(e.target.value)} style={fieldStyle} />
            </LabeledField>
            <LabeledField label="XP reward">
              <input type="number" value={xpReward} onChange={e => setXpReward(Number(e.target.value) || 0)} style={fieldStyle} />
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
              <input type="number" value={sortOrder} onChange={e => setSortOrder(Number(e.target.value) || 0)} style={fieldStyle} />
            </LabeledField>
            <div style={{ display: "flex", alignItems: "flex-end", paddingBottom: 8 }}>
              <label style={checkLabel}>
                <input type="checkbox" checked={secret} onChange={e => setSecret(e.target.checked)} /> Secret (hidden until earned)
              </label>
            </div>
          </div>
          <LabeledField label="Description">
            <textarea value={description} onChange={e => setDescription(e.target.value)} rows={2} style={fieldStyle} />
          </LabeledField>
          <button className="btn btn--primary btn--sm" onClick={save} disabled={saving} style={{ justifySelf: "start" }}>
            {saving ? "Saving…" : "Save"}
          </button>

          <div>
            <div className="label-micro" style={{ marginBottom: 6 }}>Icon</div>
            <input
              ref={fileRef}
              type="file"
              accept="image/png,image/webp,image/svg+xml"
              style={{ display: "none" }}
              onChange={e => handleFile(e.target.files?.[0])}
            />
            <div
              onClick={() => { if (!iconUploading) fileRef.current?.click(); }}
              onDragOver={e => e.preventDefault()}
              onDrop={e => { e.preventDefault(); if (!iconUploading) handleFile(e.dataTransfer.files?.[0]); }}
              style={{
                border: "1px dashed var(--border)", borderRadius: "var(--r-md)",
                padding: 14, textAlign: "center", cursor: iconUploading ? "default" : "pointer",
                fontSize: 12, color: "var(--text-muted)", opacity: iconUploading ? 0.7 : 1,
              }}
            >
              {iconUploading ? "Uploading…" : "Drop a 512×512 PNG, WebP or SVG here, or click to choose (≤512 KB)"}
            </div>
          </div>

          <div>
            <div className="label-micro" style={{ marginBottom: 6 }}>Triggers · {triggers.length}</div>
            {triggers.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>None.</div>}
            {triggers.map(t => (
              <div key={t.id} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
                <input
                  value={t.trigger_type}
                  onChange={e => updateTriggerInline(t.id, { trigger_type: e.target.value })}
                  style={{ ...fieldStyle, flex: 1 }}
                />
                <input
                  type="number"
                  value={t.trigger_threshold}
                  onChange={e => updateTriggerInline(t.id, { trigger_threshold: Number(e.target.value) || 0 })}
                  style={{ ...fieldStyle, width: 80 }}
                />
                <button className="btn btn--sm btn--ghost" onClick={() => deleteTriggerInline(t.id)}>×</button>
              </div>
            ))}
            <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 6 }}>
              <input
                placeholder="trigger_type (e.g. login_streak)"
                value={newTrigger.trigger_type}
                onChange={e => setNewTrigger(v => ({ ...v, trigger_type: e.target.value }))}
                style={{ ...fieldStyle, flex: 1 }}
              />
              <input
                type="number"
                value={newTrigger.trigger_threshold}
                onChange={e => setNewTrigger(v => ({ ...v, trigger_threshold: Number(e.target.value) || 0 }))}
                style={{ ...fieldStyle, width: 80 }}
              />
              <button className="btn btn--sm btn--primary" onClick={addTrigger}>Add</button>
            </div>
          </div>

          <div>
            <div className="label-micro" style={{ marginBottom: 6 }}>Linked cosmetics · {linkedCosmeticIds.length}</div>
            {linkedCosmeticIds.length === 0 && <div style={{ fontSize: 12, color: "var(--text-muted)" }}>None.</div>}
            {linkedCosmeticIds.map(cid => {
              const c = cosmetics.find(x => x.id === cid);
              return (
                <div key={cid} style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: 6 }}>
                  <span style={{ ...fieldStyle, flex: 1, display: "flex", alignItems: "center", gap: 8 }}>
                    <span>{c ? c.name : cid}</span>
                    {c && (
                      <span style={{ fontSize: 10, color: "var(--text-muted)", textTransform: "uppercase" }}>
                        {c.type} · {c.rarity}
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
            <div style={{ display: "flex", gap: 6, alignItems: "center", marginTop: 6 }}>
              <CustomSelect
                size="sm"
                value={pendingCosmeticId}
                onChange={setPendingCosmeticId}
                options={cosmetics
                  .filter(c => !linkedCosmeticIds.includes(c.id))
                  .map(c => ({ value: c.id, label: c.name, description: `${c.type} · ${c.rarity}` }))}
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
    <div className="card" style={{ padding: "var(--pad-lg)" }}>
      <div className="label-micro" style={{ marginBottom: 10 }}>Grant to user</div>
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
      <div style={{ fontSize: 11, color: "var(--text-muted)", marginTop: -4, marginBottom: 10 }}>
        Drafts are disabled here — publish a badge first.
      </div>
      <button
        className="btn"
        onClick={doGrant}
        disabled={granting || !grant.userId || !grant.achievementId}
        style={{ width: "100%" }}
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
    <div className="card" style={{ padding: 0 }}>
      <div style={{ padding: "12px 16px", borderBottom: "1px solid var(--border)" }}>
        <div className="label-micro">XP rules · {rules.length}</div>
      </div>
      {rules.length === 0 && (
        <div style={{ padding: 28, textAlign: "center", color: "var(--text-muted)", fontSize: 13 }}>No XP rules defined.</div>
      )}
      {rules.map(r => (
        <div key={r.key} style={{
          display: "flex", alignItems: "center", gap: 12,
          padding: "10px 16px", borderTop: "1px solid var(--border)", fontSize: 13,
        }}>
          <span style={{ flex: 1, fontWeight: 500 }}>{r.label}</span>
          <input
            type="number"
            value={drafts[r.key] ?? String(r.amount)}
            onChange={e => setDrafts(prev => ({ ...prev, [r.key]: e.target.value }))}
            onBlur={() => commitAmount(r.key)}
            onKeyDown={e => { if (e.key === "Enter") (e.target as HTMLInputElement).blur(); }}
            disabled={busyKey === r.key}
            style={{ ...fieldStyle, width: 90 }}
          />
          <label style={checkLabel}>
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
    <div style={{ marginBottom: 10 }}>
      <div className="label-micro" style={{ marginBottom: 4 }}>{label}</div>
      {children}
    </div>
  );
}

const fieldStyle: React.CSSProperties = {
  width: "100%",
  padding: "7px 10px",
  border: "1px solid var(--border)",
  borderRadius: "var(--r-sm)",
  fontSize: 13,
  background: "var(--bg-input)",
  fontFamily: "inherit",
};

const checkLabel: React.CSSProperties = {
  display: "inline-flex", alignItems: "center", gap: 6, fontSize: 12, color: "var(--text-dim)",
};
