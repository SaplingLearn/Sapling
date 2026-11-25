"use client";
import React from "react";
import Link from "next/link";
import { AnimatePresence, motion, type Variants } from "framer-motion";
import { TopBar } from "../TopBar";
import { FullHeightScreen } from "../FullHeightScreen";
import { Icon } from "../Icon";
import { useScrollLock } from "@/lib/useScrollLock";
import { Avatar } from "../Avatar";
import { CustomSelect } from "../CustomSelect";
import { ProfileView } from "../ProfileView";
import { SettingsFormSkeleton } from "../Skeleton";
import { useToast } from "../ToastProvider";
import { useUser } from "@/context/UserContext";
import {
  updateSettings,
  deleteAccount,
  updateProfile,
  checkUsername,
  fetchPublicProfile,
  uploadAvatar,
  fetchCosmetics,
  fetchCosmeticsCatalog,
  equipCosmetic,
  exportData,
  type CatalogCosmetic,
} from "@/lib/api";
import type { UserSettings, UserProfile, UserCosmetic, CosmeticType, EquippedCosmetics } from "@/lib/types";
import { useLayoutPref, type LayoutPref } from "@/lib/useLayoutPref";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { readAccountSettings } from "@/lib/accountSettings";
import { chooseAnalytics } from "@/lib/analytics";
import {
  usernameBorderColor,
  usernameMessageColor,
  usernameMessageText,
  type UsernameState,
} from "./settingsUsername";
import { humanizeError } from "@/lib/errorMessage";
import { sentenceCase } from "@/lib/sentenceCase";
import { QuizPrefsSection } from "./QuizPrefsSection";
import { Toggle } from "./SettingsToggle";
import { AnalyticsPreference } from "./AnalyticsPreference";
import { useMotionPresets, type MotionPreset } from "@/lib/motion";
import styles from "./Settings.module.css";

/** A lib/motion preset as variants: spreading its target objects straight
 *  onto a motion element fails framer 11's prop types (TS2590), variants do not. */
function presetVariants(p: MotionPreset) {
  const variants: Variants = { initial: p.initial, animate: p.animate, exit: p.exit };
  return { variants, initial: "initial", animate: "animate", exit: "exit", transition: p.transition } as const;
}

/** Accent presets. These are stored values (`user_settings.accent_color`,
 *  painted onto `--accent`), i.e. data a student picks, not design colours,
 *  so they stay literal; the first is the default. */
const ACCENT_SWATCHES = ["#2b5221", "#2b8c96", "#e8a33a", "#8a63d2", "#dc2626"] as const;
const DEFAULT_ACCENT = ACCENT_SWATCHES[0];

/** Image sizes handed to <Avatar>/<img> (px): the profile card's avatar, and a
 *  frame preview with the avatar inside it. */
const PROFILE_AVATAR_PX = 72;
const FRAME_PX = 64;
const FRAME_AVATAR_PX = 52;
const BANNER_PREVIEW_W = 180;
const BANNER_PREVIEW_H = 48;
/** Username availability check debounce. */
const USERNAME_CHECK_DEBOUNCE_MS = 400;

type Tab = "profile" | "cosmetics" | "preferences" | "notifications" | "data";

export function Settings() {
  const toast = useToast();
  const { userId, userName, avatarUrl, userReady, signOut, setAvatarUrl } = useUser();
  const [tab, setTabState] = React.useState<Tab>("profile");
  // The open tab's panel fades in on a switch, never on the first paint.
  const [tabSwitched, setTabSwitched] = React.useState(false);
  const setTab = (t: Tab) => {
    setTabSwitched(true);
    setTabState(t);
  };
  const m = useMotionPresets();
  const [settings, setSettings] = React.useState<UserSettings | null>(null);
  const [layoutPref, setLayoutPref] = useLayoutPref();
  // Per-field in-flight saves (#769): a count per settings key, so the
  // "saving…" chip stays up until the LAST overlapping save settles (one
  // shared boolean was cleared by whichever finished first) and a field's own
  // control can tell its save is still running.
  const [savingFields, setSavingFields] = React.useState<Record<string, number>>({});
  const saving = Object.keys(savingFields).length > 0;
  const trackSaving = React.useCallback((keys: string[], delta: 1 | -1) => {
    setSavingFields(prev => {
      const next = { ...prev };
      for (const k of keys) {
        const n = (next[k] ?? 0) + delta;
        if (n > 0) next[k] = n;
        else delete next[k];
      }
      return next;
    });
  }, []);
  // Rollback bookkeeping for patch() (#769). `confirmed` = the last value the
  // server accepted per key; `fieldSeq` = the latest save per key, so only
  // the newest save to a field may roll it back.
  const confirmedRef = React.useRef<Partial<UserSettings>>({});
  const fieldSeq = React.useRef<Record<string, number>>({});
  const usernameReq = useLatestRequest();
  const [previewOpen, setPreviewOpen] = React.useState(false);
  const [preview, setPreview] = React.useState<UserProfile | null>(null);
  const [usernameDraft, setUsernameDraft] = React.useState<string>("");
  const [usernameState, setUsernameState] = React.useState<UsernameState>({ status: "idle" });
  const usernameTimer = React.useRef<ReturnType<typeof setTimeout> | null>(null);

  React.useEffect(() => {
    if (!userReady || !userId) return;
    // The `/settings` payload can come back with the profile identity fields
    // (display name, username, bio, location, website) unset, which would
    // leave the Profile form blank and risk a save wiping the stored values.
    // Seed those fields from the public profile as a fallback so the inputs
    // reflect what's actually stored. The profile fetch is best-effort — a
    // failure there must not block settings from loading.
    // readAccountSettings shares one in-flight GET with the UserProvider's
    // analytics read and feeds `analytics_opt_out` to the analytics switch
    // below (lib/accountSettings.ts), so the form and the switch agree.
    Promise.all([
      readAccountSettings(userId),
      fetchPublicProfile(userId).catch(() => null),
    ])
      .then(([s, profile]) => {
        const seeded: UserSettings = {
          ...s,
          display_name: s.display_name || profile?.name || null,
          username: s.username || profile?.username || null,
          bio: s.bio || profile?.bio || null,
          location: s.location || profile?.location || null,
          website: s.website || profile?.website || null,
        };
        setSettings(seeded);
        confirmedRef.current = { ...seeded };
        setUsernameDraft(seeded.username || "");
        if (seeded.accent_color) {
          document.documentElement.style.setProperty("--accent", seeded.accent_color);
        }
      })
      .catch((e) => console.error("settings load", e));
  }, [userReady, userId]);

  // Optimistic, with rollback (#769): the control flips at once; if the save
  // fails, each field this save still owns (no newer save to it since) goes
  // back to the last value the server accepted, and the student is told.
  const patch = async (updates: Partial<UserSettings>) => {
    if (!userId || !settings) return;
    const keys = Object.keys(updates) as (keyof UserSettings)[];
    const mySeq: Record<string, number> = {};
    for (const k of keys) mySeq[k] = fieldSeq.current[k] = (fieldSeq.current[k] ?? 0) + 1;
    setSettings(prev => (prev ? { ...prev, ...updates } : prev));
    trackSaving(keys, 1);
    try {
      await updateSettings(userId, updates);
      Object.assign(confirmedRef.current, updates);
    } catch (err) {
      console.error("settings save", err);
      const owned = keys.filter(k => fieldSeq.current[k] === mySeq[k]);
      if (owned.length > 0) {
        const revert: Partial<UserSettings> = {};
        for (const k of owned) Object.assign(revert, { [k]: confirmedRef.current[k] });
        setSettings(prev => (prev ? { ...prev, ...revert } : prev));
        if ("accent_color" in revert) {
          // The accent is painted straight onto :root at pick time.
          if (revert.accent_color) document.documentElement.style.setProperty("--accent", revert.accent_color);
          else document.documentElement.style.removeProperty("--accent");
        }
        toast.error("Couldn't save that setting, so it's been changed back. Please try again.");
      }
    } finally {
      trackSaving(keys, -1);
    }
  };

  // Product analytics. The account flag is the single source of truth, for
  // this browser's pageviews and the backend's PostHog mirror alike, so it
  // is saved whether or not this browser sends anything. Opting out stops
  // capture here at once, then saves; opting in saves FIRST and only then
  // starts capture. The switch is disabled while a save is in flight, so
  // toggles cannot overlap (chooseAnalytics also refuses).
  const [analyticsSaving, setAnalyticsSaving] = React.useState(false);
  const setAnalyticsPreference = async (enabled: boolean) => {
    if (!userId || analyticsSaving) return;
    setAnalyticsSaving(true);
    try {
      const result = await chooseAnalytics(userId, enabled, (optOut) =>
        updateSettings(userId, { analytics_opt_out: optOut }),
      );
      if (result === "failed") {
        toast.error(
          enabled
            ? "Couldn't turn product analytics back on. Please try again."
            : "Couldn't save that to your account, so it's off in this browser for this visit only — retry from Settings → Data.",
        );
      }
    } finally {
      setAnalyticsSaving(false);
    }
  };

  const avatarFileRef = React.useRef<HTMLInputElement | null>(null);
  const [uploadingAvatar, setUploadingAvatar] = React.useState(false);

  const handleAvatarFile = async (file: File | null) => {
    if (!file || !userId) return;
    if (!file.type.startsWith("image/")) {
      toast.error("Pick an image file (PNG or JPG).");
      if (avatarFileRef.current) avatarFileRef.current.value = "";
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      toast.error(`That file is ${(file.size / 1024 / 1024).toFixed(1)} MB — max is 5 MB.`);
      if (avatarFileRef.current) avatarFileRef.current.value = "";
      return;
    }

    // Optimistic UI: paint the picked image immediately via a local
    // blob URL so the user sees their face in the avatar circle the
    // instant they pick the file. The actual upload + Supabase
    // round-trip can take 1–3s on slow connections; without this,
    // there's a visible delay between "Avatar updated" toast and
    // the image appearing.
    //
    // We capture the previous URL up front so we can revert on
    // failure, and revoke the blob URL once we either swap to the
    // real Supabase URL or roll back, to free its memory.
    const previousAvatar = avatarUrl;
    const blobUrl = URL.createObjectURL(file);
    setAvatarUrl(blobUrl);
    setUploadingAvatar(true);
    try {
      const result = await uploadAvatar(userId, file);
      // Swap to the canonical Supabase URL with a cache-bust so
      // re-uploads on the same deterministic path actually refresh.
      // No need to call refreshProfile() — we already have the URL,
      // and skipping the extra /api/auth/me round-trip removes ~50–
      // 200ms of latency from the perceived flow.
      const sep = result.avatar_url.includes("?") ? "&" : "?";
      setAvatarUrl(`${result.avatar_url}${sep}v=${Date.now()}`);
      toast.success("Avatar updated");
    } catch (err) {
      // Revert to whatever the user had before so the optimistic
      // paint doesn't leave a ghost of a file that never landed.
      setAvatarUrl(previousAvatar);
      toast.error(humanizeError(err, "Couldn't upload that image. Try again."));
    } finally {
      // Always free the blob URL — whether we swapped to the
      // server URL or reverted, the blob is no longer referenced.
      URL.revokeObjectURL(blobUrl);
      setUploadingAvatar(false);
      if (avatarFileRef.current) avatarFileRef.current.value = "";
    }
  };

  const patchProfile = async (updates: { username?: string; display_name?: string; bio?: string; location?: string; website?: string }) => {
    if (!userId || !settings) return;
    const keys = Object.keys(updates);
    trackSaving(keys, 1);
    try {
      await updateProfile(userId, updates);
      setSettings(prev => prev ? { ...prev, ...updates } : prev);
      Object.assign(confirmedRef.current, updates);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't save your settings. Try again."));
    } finally {
      trackSaving(keys, -1);
    }
  };

  React.useEffect(() => {
    if (usernameTimer.current) clearTimeout(usernameTimer.current);
    const next = usernameDraft.trim().toLowerCase();
    if (!next || next === (settings?.username || "")) {
      usernameReq.cancel();
      setUsernameState({ status: "idle" });
      return;
    }
    setUsernameState({ status: "checking" });
    // Clearing the debounce timer doesn't stop a check already in flight: a
    // late reply for an older draft used to mark THIS draft available (#769).
    const run = usernameReq.begin();
    usernameTimer.current = setTimeout(async () => {
      try {
        const r = await checkUsername(next, userId || undefined);
        if (!run.isCurrent()) return;
        if (r.available) setUsernameState({ status: "available", message: "Available", checked: next });
        else if (r.reason === "invalid") setUsernameState({ status: "invalid", message: "3–24 chars, lowercase letters, digits, or _", checked: next });
        else setUsernameState({ status: "taken", message: "Already taken", checked: next });
      } catch {
        if (run.isCurrent()) setUsernameState({ status: "idle" });
      }
    }, USERNAME_CHECK_DEBOUNCE_MS);
    return () => {
      if (usernameTimer.current) clearTimeout(usernameTimer.current);
      usernameReq.cancel();
    };
  }, [usernameDraft, settings?.username, userId, usernameReq]);

  const openPreview = async () => {
    if (!userId) return;
    try {
      const p = await fetchPublicProfile(userId);
      setPreview(p);
      setPreviewOpen(true);
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't load that preview."));
    }
  };

  const handleDelete = async () => {
    if (!userId) return;
    const conf = window.prompt(
      'Type "DELETE" to delete your account. It is hidden now and its personal data is erased in 30 days.',
    );
    if (conf !== "DELETE") return;
    try {
      await deleteAccount(userId, conf);
      await signOut();
      window.location.href = "/";
    } catch (err) {
      // Was a bare `alert(String(err))`: a browser dialog showing the raw
      // response body. This screen has a toaster like every other one.
      toast.error(humanizeError(err, "Couldn't delete your account. Try again."));
    }
  };

  const tabs: Tab[] = ["profile", "cosmetics", "preferences", "notifications", "data"];

  return (
    <FullHeightScreen>
      <TopBar
        title="Settings"
        subtitle="Profile, preferences, and account"
        actions={
          <>
            {saving && (
              <motion.span
                className="chip chip--accent"
                {...presetVariants(m.fade)}
              >
                saving…
              </motion.span>
            )}
            <button className="btn btn--sm" onClick={openPreview} disabled={!userId}>
              <Icon name="search" size={12} /> Preview profile
            </button>
          </>
        }
      />
      {/* Fills whatever `<main>` leaves below TopBar. `minHeight: 0` lets this
          shrink past its content so the panes below scroll internally rather
          than pushing the screen taller than `<main>`. */}
      <div className={styles.screen}>
        <div className={styles.main}>
          {!settings && tab !== "cosmetics" && <SettingsFormSkeleton />}
          <motion.div
            key={tab}
            {...presetVariants(m.fade)}
            initial={tabSwitched ? "initial" : false}
          >
            {tab === "profile" && settings && (
              <div className={styles.section}>
                <div className={`h-serif ${styles.sectionTitle}`}>Profile</div>
                <div className={`card ${styles.avatarCard}`}>
                  <Avatar name={userName || "?"} size={PROFILE_AVATAR_PX} img={avatarUrl || undefined} />
                  <div className={styles.grow}>
                    <div className={styles.userName}>
                      {userName}
                    </div>
                    <div className={styles.hint}>PNG or JPG, up to 5 MB.</div>
                  </div>
                  <input
                    ref={avatarFileRef}
                    type="file"
                    accept="image/*"
                    className={styles.fileInput}
                    onChange={e => handleAvatarFile(e.target.files?.[0] ?? null)}
                  />
                  <button className="btn btn--sm" onClick={() => avatarFileRef.current?.click()} disabled={uploadingAvatar}>
                    <Icon name="pencil" size={12} /> {uploadingAvatar ? "Uploading…" : "Change avatar"}
                  </button>
                </div>
                <div className="settings-field-row">
                  <label className="label-micro" htmlFor="settings-field-username">Username</label>
                  <div>
                    <div className={styles.usernameWrap}>
                      <span aria-hidden className={styles.at}>@</span>
                      <input
                        id="settings-field-username"
                        value={usernameDraft}
                        onChange={e => setUsernameDraft(e.target.value)}
                        onBlur={async () => {
                          const v = usernameDraft.trim().toLowerCase();
                          // Save only the draft that was actually verified (#769).
                          if (
                            v && v !== (settings.username || "")
                            && usernameState.status === "available" && usernameState.checked === v
                          ) {
                            await patchProfile({ username: v });
                          } else if (!v && settings.username) {
                            setUsernameDraft(settings.username || "");
                          }
                        }}
                        placeholder="your-handle"
                        className={`${styles.input} ${styles.usernameInput}`}
                        style={{ "--username-border": usernameBorderColor(usernameState.status) } as React.CSSProperties}
                      />
                    </div>
                    {usernameState.message && (
                      <motion.div
                        key={usernameState.status}
                        {...presetVariants(m.fade)}
                        className={styles.usernameMsg}
                        style={{ "--username-msg": usernameMessageColor(usernameState.status) } as React.CSSProperties}
                      >
                        {usernameMessageText(usernameState)}
                      </motion.div>
                    )}
                  </div>
                </div>

                {(
                  [
                    ["Display name", "display_name"],
                    ["Bio", "bio"],
                    ["Location", "location"],
                    ["Website", "website"],
                  ] as const
                ).map(([label, key]) => (
                  <div key={key} className="settings-field-row">
                    <label className="label-micro" htmlFor={`settings-field-${key}`}>{label}</label>
                    <input
                      id={`settings-field-${key}`}
                      defaultValue={settings[key] ?? ""}
                      onBlur={(e) => {
                        const v = e.target.value.trim();
                        if (v !== (settings[key] ?? "")) {
                          patchProfile({ [key]: v || undefined });
                        }
                      }}
                      className={styles.input}
                    />
                  </div>
                ))}

                <div className={`${styles.row} ${styles.signOutRow}`}>
                  <div>
                    <div className={styles.rowLabel}>Sign out</div>
                    <div className={styles.rowHint}>
                      End your session on this device.
                    </div>
                  </div>
                  <button
                    className="btn btn--sm"
                    onClick={async () => {
                      await signOut();
                      window.location.href = "/";
                    }}
                  >
                    <Icon name="logout" size={12} /> Sign out
                  </button>
                </div>
              </div>
            )}

            {tab === "cosmetics" && userId && (
              <CosmeticsManager userId={userId} />
            )}

            {tab === "preferences" && settings && (
              <div className={styles.section}>
                <div className={`h-serif ${styles.sectionTitle}`}>Preferences</div>
                <div className={`${styles.row} ${styles.ruled}`}>
                  <div>
                    <div className={styles.rowLabel}>Layout</div>
                    <div className={styles.rowHint}>
                      Choose between a top navigation bar or a full-height sidebar.
                      Falls back to top nav on small screens.
                    </div>
                  </div>
                  <div className={styles.select}>
                    <CustomSelect
                      ariaLabel="Layout"
                      size="sm"
                      value={layoutPref}
                      onChange={(v) => setLayoutPref(v as LayoutPref)}
                      options={[
                        { value: "sidebar", label: "Sidebar (default)" },
                        { value: "topnav",  label: "Top nav" },
                      ]}
                    />
                  </div>
                </div>
                {(
                  [
                    ["Theme", "theme", ["light"]],
                    ["Font size", "font_size", ["small", "medium", "large"]],
                    ["Profile visibility", "profile_visibility", ["public", "school", "private"]],
                  ] as const
                ).map(([label, key, options]) => (
                  <div key={key} className={`${styles.row} ${styles.ruled}`}>
                    <div className={styles.rowLabel}>{label}</div>
                    <div className={styles.select}>
                      <CustomSelect
                        ariaLabel={label}
                        size="sm"
                        value={(settings[key] as string) ?? options[0]}
                        onChange={(v) => patch({ [key]: v } as Partial<UserSettings>)}
                        options={options.map(o => ({ value: o, label: o[0].toUpperCase() + o.slice(1) }))}
                      />
                    </div>
                  </div>
                ))}
                <div className={`${styles.row} ${styles.ruled}`}>
                  <div>
                    <div className={styles.rowLabel}>Accent color</div>
                    <div className={styles.rowHint}>
                      Hue used for highlights and active states.
                    </div>
                  </div>
                  <div className={styles.swatches}>
                    {ACCENT_SWATCHES.map(c => {
                      const active = (settings.accent_color ?? DEFAULT_ACCENT) === c;
                      return (
                        <button
                          key={c}
                          onClick={() => {
                            document.documentElement.style.setProperty("--accent", c);
                            patch({ accent_color: c });
                          }}
                          aria-label={`Accent ${c}`}
                          className={`${styles.swatch} ${active ? styles.swatchActive : ""}`}
                          style={{ "--swatch": c } as React.CSSProperties}
                        />
                      );
                    })}
                    <label className={`${styles.swatch} ${styles.swatchCustom}`} title="Custom color">
                      <input
                        type="color"
                        value={settings.accent_color ?? DEFAULT_ACCENT}
                        onChange={e => {
                          document.documentElement.style.setProperty("--accent", e.target.value);
                          patch({ accent_color: e.target.value });
                        }}
                        className={styles.colorInput}
                      />
                    </label>
                  </div>
                </div>
                <QuizPrefsSection />
              </div>
            )}

            {tab === "notifications" && settings && (
              <div className={styles.section}>
                <div className={`h-serif ${styles.sectionTitle}`}>Notifications</div>
                {(
                  [
                    ["Email", "notification_email"],
                    ["Push", "notification_push"],
                    ["In-app", "notification_in_app"],
                    ["Activity status visible", "activity_status_visible"],
                  ] as const
                ).map(([label, key]) => (
                  <div key={key} className={styles.toggleRow}>
                    <div className={styles.toggleLabel} id={`settings-toggle-${key}-label`}>{label}</div>
                    <Toggle
                      on={Boolean(settings[key])}
                      onChange={(v) => patch({ [key]: v } as Partial<UserSettings>)}
                      disabled={Boolean(savingFields[key])}
                      ariaLabelledBy={`settings-toggle-${key}-label`}
                      testId={`settings-toggle-${key}`}
                    />
                  </div>
                ))}
              </div>
            )}

            {tab === "data" && (
              <div className={styles.section}>
                <div className={`h-serif ${styles.sectionTitle}`}>Your Data</div>
                <div className={`card ${styles.card}`}>
                  <div className={styles.cardTitle}>Export your data</div>
                  <div className={styles.cardBody}>
                    Download a JSON bundle of your sessions, notes, and knowledge graph.
                  </div>
                  <button
                    className="btn btn--sm"
                    onClick={async () => {
                      if (!userId) return;
                      try {
                        const data = await exportData(userId);
                        const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
                        const url = URL.createObjectURL(blob);
                        const a = document.createElement("a");
                        a.href = url;
                        a.download = `sapling-export.json`;
                        a.click();
                        URL.revokeObjectURL(url);
                        toast.success("Data exported.");
                      } catch (err) {
                        toast.error(humanizeError(err, "Couldn't export your data. Try again."));
                      }
                    }}
                  >
                    Export
                  </button>
                </div>

                <AnalyticsPreference
                  onChange={(enabled) => void setAnalyticsPreference(enabled)}
                  onRetry={() => void setAnalyticsPreference(false)}
                  onReload={() => {
                    // Feeds the switch through lib/accountSettings.ts; a failure
                    // shows as `unreadable` again, with this button.
                    if (userId) readAccountSettings(userId).catch(() => {});
                  }}
                  saving={analyticsSaving}
                />

                <div className={`h-serif ${styles.dangerTitle}`}>
                  Danger Zone
                </div>
                <div className={`card ${styles.dangerCard}`}>
                  <div className={styles.cardTitle}>Delete account</div>
                  <div className={styles.cardBody}>
                    Your account is hidden and you are signed out right away, and your Google and
                    Gradescope connections are removed. Your personal data is permanently erased
                    30 days later. Records without your content (AI usage and cost, usage
                    telemetry) are kept; see section 5 of the{" "}
                    <Link href="/privacy" className={styles.link}>
                      Privacy Policy
                    </Link>
                    .
                  </div>
                  <button className="btn btn--sm btn--danger" onClick={handleDelete}>Delete my account</button>
                </div>
              </div>
            )}
          </motion.div>
        </div>
        <div className={styles.rail}>
          {tabs.map((t) => (
            <button
              key={t}
              data-testid={`settings-tab-${t}`}
              aria-current={tab === t ? "true" : undefined}
              onClick={() => setTab(t)}
              className={styles.railTab}
            >
              {t}
            </button>
          ))}
          {/* Connected accounts lives at its own route so we can list providers
              independently of the in-page tab state. Styled like a tab button
              for visual continuity with the rest of the sidebar. */}
          <Link href="/settings/connections" className={styles.railLink}>
            Connected accounts ↗
          </Link>
        </div>
      </div>

      <AnimatePresence>
        {previewOpen && preview && (
          <PreviewModal key="preview" profile={preview} onClose={() => setPreviewOpen(false)} />
        )}
      </AnimatePresence>
    </FullHeightScreen>
  );
}

const COSMETIC_TAB_LABELS: Record<CosmeticType, string> = {
  avatar_frame: "Frames",
  banner: "Banners",
  name_color: "Name colors",
  title: "Titles",
};

type CosmeticView = "owned" | "catalog";

function CosmeticsManager({ userId }: { userId: string }) {
  const toast = useToast();
  const { userName, avatarUrl, refreshProfile } = useUser();
  const [subTab, setSubTab] = React.useState<CosmeticType>("avatar_frame");
  const [view, setView] = React.useState<CosmeticView>("owned");
  const [owned, setOwned] = React.useState<Record<CosmeticType, UserCosmetic[]>>({
    avatar_frame: [], banner: [], name_color: [], title: [],
  });
  const [catalog, setCatalog] = React.useState<Record<CosmeticType, CatalogCosmetic[]>>({
    avatar_frame: [], banner: [], name_color: [], title: [],
  });
  const [equipped, setEquipped] = React.useState<EquippedCosmetics>({});
  const [busy, setBusy] = React.useState(false);

  const load = React.useCallback(async () => {
    try {
      const [r, c] = await Promise.all([
        fetchCosmetics(userId),
        fetchCosmeticsCatalog(userId),
      ]);
      setOwned(r.cosmetics);
      setEquipped(r.equipped as EquippedCosmetics);
      setCatalog(c.catalog);
    } catch (err) {
      console.error("cosmetics load", err);
    }
  }, [userId]);

  React.useEffect(() => { load(); }, [load]);

  const equippedId = equipped[subTab]?.id ?? null;

  const equip = async (cosmeticId: string | null) => {
    setBusy(true);
    try {
      await equipCosmetic(userId, subTab, cosmeticId);
      await load();
      await refreshProfile();
      toast.success(cosmeticId ? "Equipped" : "Unequipped");
    } catch (err) {
      toast.error(humanizeError(err, "Couldn't update that. Try again."));
    } finally {
      setBusy(false);
    }
  };

  const ownedList = owned[subTab] || [];
  const catalogList = catalog[subTab] || [];
  const lockedCount = catalogList.filter(c => !c.owned).length;
  const m = useMotionPresets();
  // Each grid is keyed by what it lists, so a new sub-tab, view or a load
  // staggers its cards in.
  const gridKey = `${subTab}-${view}-${view === "owned" ? ownedList.length : catalogList.length}`;

  return (
    <div className={styles.sectionWide}>
      <div className={`h-serif ${styles.sectionTitleTight}`}>Cosmetics</div>
      <div className={styles.cosmeticBar}>
        <div className={styles.cosmeticTabs}>
          {(Object.keys(COSMETIC_TAB_LABELS) as CosmeticType[]).map(t => (
            <button
              key={t}
              onClick={() => setSubTab(t)}
              className={`${styles.cosmeticTab} ${subTab === t ? styles.cosmeticTabActive : ""}`}
            >
              {COSMETIC_TAB_LABELS[t]}
            </button>
          ))}
        </div>
        <div className={styles.viewSwitch}>
          {(["owned", "catalog"] as const).map(v => (
            <button
              key={v}
              onClick={() => setView(v)}
              className={`${styles.viewBtn} ${view === v ? styles.viewBtnActive : ""}`}
            >
              {v === "catalog" ? `Catalog · ${catalogList.length}` : `Owned · ${ownedList.length}`}
            </button>
          ))}
        </div>
      </div>

      {view === "owned" ? (
        ownedList.length === 0 ? (
          <div className={`card ${styles.empty}`}>
            No {COSMETIC_TAB_LABELS[subTab].toLowerCase()} unlocked yet.
            {catalogList.length > 0 && (
              <div className={styles.emptyAction}>
                <button className="btn btn--sm" onClick={() => setView("catalog")}>
                  Browse catalog ({catalogList.length})
                </button>
              </div>
            )}
          </div>
        ) : (
          <motion.div
            key={gridKey}
            className={styles.grid}
            variants={m.list.container}
            initial="hidden"
            animate="shown"
          >
            {ownedList.map(uc => {
              const c = uc.cosmetic;
              const isEquipped = equippedId === c.id;
              return (
                <CosmeticCard
                  key={c.id}
                  cosmetic={c}
                  userName={userName}
                  avatarUrl={avatarUrl}
                  isEquipped={isEquipped}
                  locked={false}
                  disabled={busy}
                  onClick={() => equip(isEquipped ? null : c.id)}
                />
              );
            })}
          </motion.div>
        )
      ) : (
        <>
          {catalogList.length === 0 ? (
            <div className={`card ${styles.empty}`}>
              Nothing in the catalog yet.
            </div>
          ) : (
            <motion.div
              key={gridKey}
              className={styles.grid}
              variants={m.list.container}
              initial="hidden"
              animate="shown"
            >
              {catalogList.map(c => {
                const isEquipped = equippedId === c.id;
                return (
                  <CosmeticCard
                    key={c.id}
                    cosmetic={c}
                    userName={userName}
                    avatarUrl={avatarUrl}
                    isEquipped={isEquipped}
                    locked={!c.owned}
                    unlockSource={c.unlock_source}
                    disabled={busy}
                    onClick={c.owned ? () => equip(isEquipped ? null : c.id) : undefined}
                  />
                );
              })}
            </motion.div>
          )}
          {lockedCount > 0 && (
            <div className={styles.lockedNote}>
              {lockedCount} locked · earn achievements or unlock via the ways shown on each card.
            </div>
          )}
        </>
      )}
    </div>
  );
}

function CosmeticCard({
  cosmetic, userName, avatarUrl, isEquipped, locked, unlockSource, disabled, onClick,
}: {
  cosmetic: UserCosmetic["cosmetic"];
  userName: string;
  avatarUrl: string;
  isEquipped: boolean;
  locked: boolean;
  unlockSource?: string | null;
  disabled: boolean;
  onClick?: () => void;
}) {
  const m = useMotionPresets();
  return (
    <motion.div
      variants={m.list.item}
      className={[
        "card",
        styles.cosmeticCard,
        isEquipped ? styles.cosmeticEquipped : "",
        locked ? styles.cosmeticLocked : "",
      ].join(" ")}
      style={{ "--rarity-color": `var(--rarity-${cosmetic.rarity}, var(--border))` } as React.CSSProperties}
    >
      {locked && (
        <span
          className={`chip ${styles.lockChip}`}
          title={unlockSource || "Locked"}
        >
          🔒 locked
        </span>
      )}
      <CosmeticPreview cosmetic={cosmetic} userName={userName} avatarUrl={avatarUrl} />
      <div className={styles.cosmeticName}>{cosmetic.name}</div>
      <div className={styles.rarity}>{sentenceCase(cosmetic.rarity)}</div>
      {locked ? (
        <div className={styles.unlock}>
          {unlockSource ? `Unlock: ${unlockSource}` : "Locked"}
        </div>
      ) : (
        <button
          className={`btn btn--sm ${isEquipped ? "" : "btn--primary"} ${styles.fullWidth}`}
          onClick={onClick}
          disabled={disabled || !onClick}
        >
          {isEquipped ? "Unequip" : "Equip"}
        </button>
      )}
    </motion.div>
  );
}

function CosmeticPreview({
  cosmetic, userName, avatarUrl,
}: {
  cosmetic: UserCosmetic["cosmetic"];
  userName: string;
  avatarUrl: string;
}) {
  if (cosmetic.type === "avatar_frame") {
    return (
      <div className={styles.frame}>
        <Avatar name={userName || "?"} size={FRAME_AVATAR_PX} img={avatarUrl || undefined} />
        {cosmetic.asset_url && (
          <img
            src={cosmetic.asset_url}
            alt=""
            width={FRAME_PX}
            height={FRAME_PX}
            loading="lazy"
            decoding="async"
            className={styles.frameImg}
          />
        )}
      </div>
    );
  }
  if (cosmetic.type === "banner" && cosmetic.asset_url) {
    return (
      <div className={styles.banner}>
        <img
          src={cosmetic.asset_url}
          alt=""
          width={BANNER_PREVIEW_W}
          height={BANNER_PREVIEW_H}
          loading="lazy"
          decoding="async"
          className={styles.bannerImg}
        />
      </div>
    );
  }
  if (cosmetic.type === "name_color") {
    const css = cosmetic.css_value || "var(--text)";
    const isGradient = /gradient\(/i.test(css);
    return (
      <div
        className={`h-serif ${isGradient ? styles.nameGradient : styles.nameColor}`}
        style={{ "--name-color": css } as React.CSSProperties}
      >
        {userName || "Preview"}
      </div>
    );
  }
  if (cosmetic.type === "title") {
    return (
      <span className={`chip ${styles.titleChip}`}>
        {cosmetic.css_value || cosmetic.name}
      </span>
    );
  }
  return null;
}

function PreviewModal({ profile, onClose }: { profile: UserProfile; onClose: () => void }) {
  // This modal only exists while it's open, so the lock is unconditional.
  useScrollLock(true);

  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [onClose]);

  const m = useMotionPresets();
  return (
    <motion.div onClick={onClose} className={styles.backdrop} {...presetVariants(m.fade)}>
      <motion.div onClick={e => e.stopPropagation()} className={styles.dialog} {...presetVariants(m.scaleIn)}>
        <div className={styles.dialogHead}>
          <div className="label-micro">Profile preview</div>
          <button className="btn btn--sm btn--ghost" onClick={onClose} aria-label="Close">
            <Icon name="x" size={12} /> Close
          </button>
        </div>
        <div className={styles.dialogBody}>
          <ProfileView profile={profile} embedded />
        </div>
      </motion.div>
    </motion.div>
  );
}
