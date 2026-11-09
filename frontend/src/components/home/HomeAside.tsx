"use client";
/**
 * Home's right column (Sapling Home v2): level + streak indicators with
 * hover pop-ups, Last Session, Roadmap, Recent Notes and Coming Up.
 * Presentational: the Dashboard derives every value it shows.
 */
import React from "react";
import Link from "next/link";
import { Icon } from "../Icon";
import { STATUS, type RoadmapRow, type Tier } from "./homeModel";
import styles from "./Home.module.css";

const H2: React.CSSProperties = { fontFamily: "var(--font-serif)", fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em" };
const FLAME = "M12 2c.6 3.2-1 5.1-2.6 6.9C7.8 10.7 6 12.6 6 15.6 6 19.1 8.7 22 12 22s6-2.9 6-6.4c0-2.4-1.1-4.3-2.4-5.8-.2 1.5-.9 2.7-2 3.3.4-3.9-.7-8.4-1.6-11.1z";
const FLAME_INNER = "m.2 11.6c1.6 1.2 2.6 2.6 2.6 4.1 0 1.7-1.3 2.8-2.8 2.8s-2.8-1.1-2.8-2.8c0-1.6 1.3-2.8 3-4.1z";

export function Chevron({ size = 12 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 12 12" aria-hidden="true" style={{ flexShrink: 0 }}>
      <path d="M4 2l4 4-4 4" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export type LevelInfo = { level: number; have: number; need: number; pct: number };
export type WeekFlame = { d: string; done: boolean; key: string };

const POP_WRAP: React.CSSProperties = { position: "absolute", left: 0, top: "100%", paddingTop: 8, zIndex: 40 };

export function LevelStreak({ level, streak, best, week }: { level: LevelInfo | null; streak: number; best: number | null; week: WeekFlame[] }) {
  const [pop, setPop] = React.useState<"lvl" | "stk" | null>(null);
  const hide = () => setPop(null);
  const fmt = (n: number) => n.toLocaleString("en-US");
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
      {level && (
        <div data-testid="home-level" onMouseEnter={() => setPop("lvl")} onMouseLeave={hide} style={{ position: "relative" }}>
          <span
            aria-label={`Profile level ${level.level}`}
            tabIndex={0}
            onFocus={() => setPop("lvl")}
            onBlur={hide}
            className={styles.focusRing}
            style={{ cursor: "default", display: "inline-flex", alignItems: "center", gap: 6, fontSize: 18, fontWeight: 700, color: "#445D22" }}
          >
            <Icon name="leaf" size={20} />
            <span style={{ color: "#1A1814" }}>Lvl {level.level}</span>
          </span>
          {pop === "lvl" && (
            <div style={POP_WRAP}>
              <div
                role="tooltip"
                style={{
                  width: 280, height: 124, boxSizing: "border-box", justifyContent: "space-between", background: "#FDFCF9",
                  border: "1px solid rgba(42,39,31,0.14)", borderRadius: 14, boxShadow: "0 16px 40px rgba(25,37,11,0.16)",
                  padding: "14px 16px", display: "flex", flexDirection: "column", gap: 10,
                }}
              >
                <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
                  <span style={{ fontFamily: "var(--font-serif)", fontSize: 18, fontWeight: 600 }}>Level {level.level}</span>
                </div>
                <div style={{ height: 8, borderRadius: 4, background: "#E6E2D9", overflow: "hidden" }}>
                  <div style={{ width: `${level.pct}%`, height: "100%", borderRadius: 4, background: "#5E8A36" }} />
                </div>
                <div style={{ display: "flex", justifyContent: "space-between", fontSize: 14 }}>
                  <span><strong style={{ fontWeight: 700 }}>{fmt(level.have)}</strong> <span style={{ color: "#6F6857" }}>/ {fmt(level.need)} XP</span></span>
                  <span style={{ fontWeight: 700, color: "#445D22" }}>{fmt(Math.max(0, level.need - level.have))} XP to go</span>
                </div>
              </div>
            </div>
          )}
        </div>
      )}
      <div data-testid="home-streak" onMouseEnter={() => setPop("stk")} onMouseLeave={hide} style={{ position: "relative" }}>
        <span
          aria-label={`${streak} day study streak`}
          tabIndex={0}
          onFocus={() => setPop("stk")}
          onBlur={hide}
          className={styles.focusRing}
          style={{ cursor: "default", display: "inline-flex", alignItems: "center", gap: 6, fontSize: 18, fontWeight: 700, color: "#C06020" }}
        >
          <svg width="20" height="20" viewBox="5 2 14 20" fill="#EE7A3B" aria-hidden="true"><path d={FLAME + FLAME_INNER} /></svg>
          <span style={{ color: "#1A1814" }}>{streak} {streak === 1 ? "day" : "days"}</span>
        </span>
        {pop === "stk" && (
          <div style={POP_WRAP}>
            <div
              role="tooltip"
              style={{
                width: 280, boxSizing: "border-box", background: "#FDFCF9", border: "1px solid #F3DCCB", borderRadius: 18,
                boxShadow: "0 16px 40px rgba(120,60,20,0.14)", padding: "14px 16px", display: "flex", flexDirection: "column", gap: 12,
              }}
            >
              <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                <svg width="16" height="22" viewBox="5 2 14 20" fill="#EE7A3B" aria-hidden="true" style={{ flexShrink: 0 }}><path d={FLAME + FLAME_INNER} /></svg>
                <span style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
                  <span style={{ fontFamily: "var(--font-serif)", fontSize: 24, fontWeight: 600, lineHeight: 1, color: "#B4562C" }}>{streak}</span>
                  <span style={{ fontSize: 15, color: "#3F3B31" }}>{streak === 1 ? "Day in a Row" : "Days in a Row"}</span>
                </span>
                {best !== null && best > 0 && (
                  <span style={{ marginLeft: "auto", fontSize: 13, color: "#6F6857", whiteSpace: "nowrap" }}>Best {best}</span>
                )}
              </div>
              <div style={{ display: "grid", gridTemplateColumns: "repeat(7, 1fr)", gap: 4 }}>
                {week.map((w) => (
                  <div key={w.key} style={{ display: "flex", justifyContent: "center" }}>
                    <span data-testid="home-streak-day" data-done={w.done} style={{ position: "relative", width: 26, height: 34, display: "block" }}>
                      <svg width="26" height="34" viewBox="4.5 1.5 15 21" aria-hidden="true" style={{ position: "absolute", inset: 0 }}>
                        <path d={FLAME} fill={w.done ? "#EE7A3B" : "none"} stroke="#EE7A3B" strokeWidth="1.3" strokeLinejoin="round" />
                      </svg>
                      <span style={{ position: "absolute", left: 0, right: 0, top: 17, textAlign: "center", fontSize: 10, lineHeight: "12px", fontWeight: 700, color: w.done ? "#FFFFFF" : "#C06020" }}>
                        {w.d}
                      </span>
                    </span>
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

export function StatusLine({ tier }: { tier: Tier }) {
  const s = STATUS[tier];
  return (
    <span style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 14, color: s.text, fontWeight: 600 }}>
      <span style={{ width: 8, height: 8, borderRadius: "50%", background: s.bar }} />
      {s.word}
    </span>
  );
}

export function LastSession({ session }: {
  session: { id: string; topic: string; day: string; tier: Tier | null; href: string } | null;
}) {
  return (
    <section aria-label="Last session" data-testid="home-last-session" style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <span style={H2}>Last Session</span>
        {session && <span style={{ fontSize: 14, color: "#6F6857" }}>{session.day}</span>}
      </div>
      <div
        style={{
          display: "flex", alignItems: "center", gap: 14, minHeight: 68, boxSizing: "border-box", padding: "12px 16px 12px 18px",
          background: "#EBF0E1", border: "1px solid #D3DEC2", borderRadius: 14,
        }}
      >
        <span style={{ color: "#597536", display: "flex", flexShrink: 0, transform: "translateY(-3px)" }}><Icon name="clover" size={32} /></span>
        <span style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 2 }}>
          <span style={{ fontSize: 16, fontWeight: 700, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>
            {session ? session.topic : "No sessions yet"}
          </span>
          {session?.tier ? <StatusLine tier={session.tier} /> : (
            <span style={{ fontSize: 14, color: "#6F6857" }}>{session ? "Tutor session" : "Start one with the tutor"}</span>
          )}
        </span>
        <Link
          href={session ? session.href : "/learn"}
          data-testid={session ? `dashboard-resume-${session.id}` : "home-last-session-start"}
          className={styles.link}
          style={{ display: "inline-flex", alignItems: "center", gap: 6, fontSize: 15, fontWeight: 700, whiteSpace: "nowrap" }}
        >
          {session ? "Go back" : "Start"}
          <Chevron size={11} />
        </Link>
      </div>
    </section>
  );
}

export function Roadmap({ rows }: { rows: RoadmapRow[] }) {
  return (
    <section aria-label="Roadmap" data-testid="home-roadmap" style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={H2}>Roadmap</div>
      {rows.length === 0 && (
        <div style={{ fontSize: 14, color: "#6F6857" }}>Your roadmap appears once your courses have concepts.</div>
      )}
      {rows.map((g) => (
        <div key={g.key} data-testid="home-roadmap-row" style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          <div style={{ display: "flex", alignItems: "baseline", gap: 8 }}>
            <span style={{ fontWeight: 700, minWidth: 0, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{g.title}</span>
            <span style={{ marginLeft: "auto", fontSize: 14, color: "#3F3B31", whiteSpace: "nowrap" }}>{g.count}</span>
          </div>
          <div style={{ display: "flex", gap: 3, height: 10 }}>
            {g.segs.map((c, i) => <span key={i} style={{ flex: 1, borderRadius: 5, background: c }} />)}
          </div>
          <div style={{ fontSize: 14, color: "#6F6857" }}>{g.note}</div>
        </div>
      ))}
    </section>
  );
}

export type NoteRow = { id: string; title: string; meta: string };

export function RecentNotes({ notes }: { notes: NoteRow[] }) {
  return (
    <section
      aria-label="Recent notes"
      data-testid="home-recent-notes"
      style={{ display: "flex", flexDirection: "column", gap: 12, borderTop: "1px solid rgba(42,39,31,0.10)", paddingTop: 18 }}
    >
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
        <span style={H2}>Recent Notes</span>
        <Link href="/notetaker" className={styles.link} style={{ fontSize: 14, fontWeight: 700 }}>Add note +</Link>
      </div>
      {notes.length === 0 && <div style={{ fontSize: 14, color: "#6F6857" }}>No notes yet.</div>}
      {notes.map((n) => (
        <Link key={n.id} href={`/notetaker?note=${encodeURIComponent(n.id)}`} className={styles.noteLink} style={{ display: "flex", flexDirection: "column", gap: 2 }}>
          <span className={styles.noteTitle} style={{ fontSize: 16, fontWeight: 700 }}>{n.title} ↗</span>
          <span style={{ fontSize: 13, color: "#6F6857" }}>{n.meta}</span>
        </Link>
      ))}
    </section>
  );
}

export type UpcomingRow = { id: string; dow: string; day: string; title: string; course: string; color: string; exam: boolean };

export function ComingUp({ rows, showCalendar }: { rows: UpcomingRow[]; showCalendar: boolean }) {
  return (
    <section aria-label="Coming up" data-testid="home-coming-up" style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginBottom: 6 }}>
        <span style={H2}>Coming Up</span>
        {showCalendar && <Link href="/calendar" className={styles.link} style={{ fontSize: 14, fontWeight: 700 }}>Calendar</Link>}
      </div>
      {rows.length === 0 && <div style={{ fontSize: 14, color: "#6F6857" }}>Nothing due soon.</div>}
      {rows.map((u) => (
        <div key={u.id} data-testid="home-coming-up-row" style={{ display: "flex", alignItems: "center", gap: 12, padding: "7px 0" }}>
          <span style={{ width: 40, textAlign: "center", flexShrink: 0 }}>
            <span style={{ display: "block", fontFamily: "var(--font-mono)", fontSize: 10, letterSpacing: "0.1em", color: "#6F6857" }}>{u.dow}</span>
            <span style={{ display: "block", fontFamily: "var(--font-serif)", fontSize: 20, fontWeight: 600, lineHeight: 1 }}>{u.day}</span>
          </span>
          <span style={{ width: 4, alignSelf: "stretch", borderRadius: 2, background: u.color }} />
          <span style={{ flex: 1, minWidth: 0 }}>
            <span style={{ display: "block", fontWeight: u.exam ? 800 : 600 }}>{u.title}</span>
            <span style={{ display: "block", fontSize: 13, color: "#6F6857" }}>{u.course}</span>
          </span>
        </div>
      ))}
    </section>
  );
}
