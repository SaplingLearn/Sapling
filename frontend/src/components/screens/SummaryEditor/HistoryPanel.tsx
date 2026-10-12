"use client";
import React from "react";
import { listSummaryDocVersions, restoreSummaryDocVersion } from "@/lib/api";
import type { SummaryDocCore, SummaryDocVersion } from "@/lib/types";

const TRIGGER_LABELS: Record<string, string> = {
  initial: "Created",
  ai_edit_kept: "AI edit kept",
  source_added: "Source added",
  source_removed: "Source removed",
  restored: "Restored from an earlier version",
};

export interface HistoryPanelProps {
  summaryDocId: string;
  userId: string;
  onDocChanged: (doc: SummaryDocCore) => void;
}

export function HistoryPanel({ summaryDocId, userId, onDocChanged }: HistoryPanelProps) {
  const [versions, setVersions] = React.useState<SummaryDocVersion[]>([]);
  const [restoringId, setRestoringId] = React.useState<string | null>(null);

  const load = React.useCallback(async () => {
    const { versions: v } = await listSummaryDocVersions(summaryDocId, userId);
    setVersions(v);
  }, [summaryDocId, userId]);

  React.useEffect(() => {
    load();
  }, [load]);

  const restore = async (versionId: string) => {
    setRestoringId(versionId);
    try {
      const doc = await restoreSummaryDocVersion(summaryDocId, userId, versionId);
      onDocChanged(doc);
      await load();
    } finally {
      setRestoringId(null);
    }
  };

  if (versions.length === 0) {
    return <p style={{ fontSize: 12, color: "var(--text-muted)" }}>No earlier versions yet.</p>;
  }

  return (
    <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 10 }}>
      {versions.map((v) => (
        <li key={v.id} style={{ border: "1px solid var(--border)", borderRadius: "var(--r-xs)", padding: 10 }}>
          <div className="label-micro">{TRIGGER_LABELS[v.trigger] ?? v.trigger}</div>
          <div style={{ fontSize: 11, color: "var(--text-muted)", margin: "2px 0 6px" }}>
            {new Date(v.created_at).toLocaleString()}
          </div>
          <div style={{ fontSize: 12, color: "var(--text-dim)", marginBottom: 8 }}>{v.preview}</div>
          <button
            type="button"
            className="btn btn--sm"
            disabled={restoringId === v.id}
            onClick={() => restore(v.id)}
          >
            Bring this back
          </button>
        </li>
      ))}
    </ul>
  );
}
