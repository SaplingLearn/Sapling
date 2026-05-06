"use client";
import { TopBar } from "@/components/TopBar";
import { Icon } from "@/components/Icon";

export default function NotetakerPage() {
  return (
    <div style={{ display: "flex", height: "100vh", flexDirection: "column" }}>
      <TopBar title="Notetaker" />
      <main
        style={{
          flex: 1,
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          padding: 32,
          gap: 14,
          textAlign: "center",
        }}
      >
        <div
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 8,
            padding: "6px 14px",
            borderRadius: "var(--r-full)",
            background: "var(--accent-soft)",
            color: "var(--accent)",
            fontSize: 12,
            fontWeight: 600,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          <Icon name="sparkle" size={12} />
          Coming soon
        </div>
        <div className="h-serif" style={{ fontSize: 28, fontWeight: 500 }}>
          Notetaker
        </div>
        <div style={{ color: "var(--text-dim)", fontSize: 14, maxWidth: 480, lineHeight: 1.55 }}>
          Capture lecture notes, link them to concepts in your knowledge graph, and let
          Sapling turn them into review material. We&apos;re still building it — check back
          soon.
        </div>
      </main>
    </div>
  );
}
