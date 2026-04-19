"use client";
import React from "react";
import { AvatarFrame } from "./AvatarFrame";
import { NameColorRenderer } from "./NameColorRenderer";
import { TitleFlair } from "./TitleFlair";
import { RoleBadge } from "./RoleBadge";
import { Icon } from "./Icon";
import type { UserProfile } from "@/lib/types";

const rarityColor: Record<string, string> = {
  common: "#8a8372",
  uncommon: "#4e873c",
  rare: "#3e6f8a",
  epic: "#7b4b99",
  legendary: "#b4862c",
};

export function ProfileView({ profile, embedded = false }: { profile: UserProfile; embedded?: boolean }) {
  const eq = profile.equipped_cosmetics || {};
  const roles = [...(profile.roles || [])].sort(
    (a, b) => (b.role.display_priority || 0) - (a.role.display_priority || 0),
  );

  const hero = (
    <section
      style={{
        display: "flex",
        gap: 20,
        alignItems: "flex-start",
        padding: "var(--pad-lg)",
        background: eq.banner?.asset_url
          ? `linear-gradient(135deg, color-mix(in oklab, ${eq.banner.css_value || "var(--accent)"} 35%, var(--bg-panel)) 0%, var(--bg-panel) 100%)`
          : "var(--bg-panel)",
        border: "1px solid var(--border)",
        borderRadius: "var(--r-xl)",
        position: "relative",
        overflow: "hidden",
      }}
    >
      <div>
        <AvatarFrame
          name={profile.name || "?"}
          size={88}
          img={profile.avatar_url || undefined}
          frame={eq.avatar_frame ?? null}
        />
      </div>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <NameColorRenderer
            name={profile.name || "Unnamed"}
            cosmetic={eq.name_color ?? null}
            as="h1"
            style={{ fontFamily: "var(--font-display)", fontSize: 26, fontWeight: 500, margin: 0 }}
          />
          {eq.title && <TitleFlair cosmetic={eq.title} />}
        </div>
        {profile.username && (
          <div style={{ fontSize: 12, color: "var(--text-muted)", marginTop: 4 }}>
            @{profile.username}
          </div>
        )}
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginTop: 10 }}>
          {roles.map(r => (
            <RoleBadge key={r.role.id} role={r.role} />
          ))}
        </div>
        {profile.bio && (
          <p style={{ margin: "12px 0 0", fontSize: 13, color: "var(--text-dim)", lineHeight: 1.55 }}>
            {profile.bio}
          </p>
        )}
        <div style={{ display: "flex", gap: 14, flexWrap: "wrap", marginTop: 12, fontSize: 12, color: "var(--text-muted)" }}>
          {profile.school && <Meta icon="tree" text={profile.school} />}
          {profile.year && <Meta icon="star" text={profile.year} />}
          {profile.location && <Meta icon="home" text={profile.location} />}
          {profile.website && (
            <a
              href={profile.website}
              target="_blank"
              rel="noreferrer"
              style={{ color: "var(--accent)", textDecoration: "underline", display: "inline-flex", alignItems: "center", gap: 4 }}
            >
              <Icon name="send" size={11} /> {prettyUrl(profile.website)}
            </a>
          )}
        </div>
      </div>
    </section>
  );

  const studies = [
    profile.majors?.length && { label: "Majors", values: profile.majors },
    profile.minors?.length && { label: "Minors", values: profile.minors },
  ].filter(Boolean) as { label: string; values: string[] }[];

  const stats = profile.stats || ({} as UserProfile["stats"]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16, padding: embedded ? 0 : "20px 0", maxWidth: 900, margin: "0 auto" }}>
      {hero}

      {(stats.streak_count !== undefined || stats.session_count !== undefined) && (
        <section style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: 12 }}>
          <StatCard label="Streak" value={stats.streak_count ?? 0} suffix="days" />
          <StatCard label="Sessions" value={stats.session_count ?? 0} />
          <StatCard label="Documents" value={stats.documents_count ?? 0} />
          <StatCard label="Achievements" value={stats.achievements_count ?? 0} />
        </section>
      )}

      {studies.length > 0 && (
        <section className="card" style={{ padding: "var(--pad-lg)" }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Fields of study</div>
          <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
            {studies.map(s => (
              <div key={s.label} style={{ display: "flex", gap: 10, alignItems: "baseline" }}>
                <div style={{ fontSize: 12, color: "var(--text-muted)", minWidth: 60 }}>{s.label}</div>
                <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
                  {s.values.map(v => (
                    <span key={v} className="chip">{v}</span>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </section>
      )}

      {(profile.featured_achievements?.length ?? 0) > 0 && (
        <section className="card" style={{ padding: "var(--pad-lg)" }}>
          <div className="label-micro" style={{ marginBottom: 10 }}>Featured achievements</div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fill, minmax(140px, 1fr))", gap: 10 }}>
            {profile.featured_achievements!.map(ua => {
              const c = rarityColor[ua.achievement.rarity] || "var(--text-muted)";
              return (
                <div
                  key={ua.achievement.id}
                  style={{
                    padding: 12,
                    textAlign: "center",
                    border: `1px solid ${c}33`,
                    background: `${c}0f`,
                    borderRadius: "var(--r-md)",
                    borderTop: `3px solid ${c}`,
                  }}
                >
                  <div style={{ fontSize: 26, marginBottom: 4 }}>{ua.achievement.icon || "★"}</div>
                  <div style={{ fontSize: 11, fontWeight: 600 }}>{ua.achievement.name}</div>
                  <div style={{ fontSize: 10, color: "var(--text-muted)", marginTop: 2, textTransform: "uppercase", letterSpacing: "0.08em" }}>
                    {ua.achievement.rarity}
                  </div>
                </div>
              );
            })}
          </div>
        </section>
      )}

      {profile.stats === undefined || Object.keys(profile.stats || {}).length === 0 ? (
        <div style={{ fontSize: 12, color: "var(--text-muted)", textAlign: "center", padding: 24 }}>
          This profile is private.
        </div>
      ) : null}
    </div>
  );
}

function Meta({ icon, text }: { icon: string; text: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
      <Icon name={icon} size={11} />
      {text}
    </span>
  );
}

function StatCard({ label, value, suffix }: { label: string; value: number; suffix?: string }) {
  return (
    <div className="card" style={{ padding: "14px 16px" }}>
      <div className="label-micro">{label}</div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 4, marginTop: 2 }}>
        <div className="mono" style={{ fontSize: 22, fontWeight: 600 }}>{value}</div>
        {suffix && <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{suffix}</div>}
      </div>
    </div>
  );
}

function prettyUrl(url: string) {
  try {
    const u = new URL(url);
    return u.hostname.replace(/^www\./, "") + (u.pathname !== "/" ? u.pathname : "");
  } catch {
    return url;
  }
}
