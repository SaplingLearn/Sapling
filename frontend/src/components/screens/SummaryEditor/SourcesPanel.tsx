"use client";
import React from "react";
import { addSummaryDocSource, removeSummaryDocSource, getDocuments } from "@/lib/api";
import type { SummaryDoc, Document as Doc } from "@/lib/types";
import { useToast } from "../../ToastProvider";

export interface SourcesPanelProps {
  doc: SummaryDoc;
  userId: string;
  onDocChanged: (doc: SummaryDoc) => void;
}

export function SourcesPanel({ doc, userId, onDocChanged }: SourcesPanelProps) {
  const toast = useToast();
  const [library, setLibrary] = React.useState<Doc[]>([]);
  const [busyId, setBusyId] = React.useState<string | null>(null);

  React.useEffect(() => {
    getDocuments(userId)
      .then((r) => setLibrary(r.documents || []))
      .catch(() => setLibrary([]));
  }, [userId]);

  const sourceIds = new Set(doc.sources.map((s) => s.document_id));
  const addable = library.filter((d) => !sourceIds.has(d.id));

  const add = async (documentId: string) => {
    setBusyId(documentId);
    try {
      const updated = await addSummaryDocSource(doc.id, userId, documentId);
      onDocChanged(updated);
    } catch (err) {
      toast.error(`Couldn't add that source: ${String((err as Error)?.message || err)}`);
    } finally {
      setBusyId(null);
    }
  };

  const remove = async (documentId: string) => {
    setBusyId(documentId);
    try {
      const result = await removeSummaryDocSource(doc.id, userId, documentId);
      onDocChanged(result);
    } catch (err) {
      toast.error(`Couldn't remove that source: ${String((err as Error)?.message || err)}`);
    } finally {
      setBusyId(null);
    }
  };

  return (
    <div>
      <ul style={{ listStyle: "none", margin: 0, padding: 0, display: "flex", flexDirection: "column", gap: 6 }}>
        {doc.sources.map((s) => (
          <li key={s.document_id} style={{ display: "flex", alignItems: "center", gap: 6, fontSize: 13 }}>
            <span style={{ flex: 1, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
              {s.file_name}
            </span>
            {s.document_id !== doc.primary_document_id && (
              <button
                type="button"
                className="btn btn--ghost btn--sm"
                aria-label={`Remove ${s.file_name}`}
                disabled={busyId === s.document_id}
                onClick={() => remove(s.document_id)}
              >
                ✕
              </button>
            )}
          </li>
        ))}
      </ul>
      {addable.length > 0 && (
        <div style={{ marginTop: 12 }}>
          <div className="label-micro" style={{ marginBottom: 6 }}>Add a source</div>
          {addable.map((d) => (
            <button
              key={d.id}
              type="button"
              className="btn btn--sm"
              style={{ width: "100%", marginBottom: 4, justifyContent: "flex-start" }}
              disabled={busyId === d.id}
              onClick={() => add(d.id)}
            >
              + {d.file_name}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
