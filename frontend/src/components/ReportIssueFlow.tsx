"use client";

import React, { useCallback, useRef, useState } from "react";
import { Icon } from "./Icon";
import { Pill } from "./Pill";
import { useToast } from "./ToastProvider";
import { useUser } from "@/context/UserContext";
import { useBodyScrollLock } from "@/lib/useBodyScrollLock";
import { supabase } from "@/lib/supabase";
import { submitIssueReport, IS_LOCAL_MODE } from "@/lib/api";

const TOPICS = ["Bug", "Feature", "Polish", "Content", "Other"] as const;
type Topic = typeof TOPICS[number];

const BUCKET = "issues-media-files";
const MAX_SCREENSHOTS = 5;
const MAX_BYTES = 5 * 1024 * 1024;

interface ReportIssueFlowProps {
  open: boolean;
  onClose: () => void;
}

async function uploadScreenshot(userId: string, file: File): Promise<string> {
  if (IS_LOCAL_MODE) return URL.createObjectURL(file);
  const ext = file.name.split(".").pop() || "png";
  const path = `${userId}/${Date.now()}-${Math.random().toString(36).slice(2, 8)}.${ext}`;
  const { error } = await supabase.storage.from(BUCKET).upload(path, file, { cacheControl: "3600", upsert: false });
  if (error) throw error;
  const { data } = supabase.storage.from(BUCKET).getPublicUrl(path);
  return data.publicUrl;
}

export function ReportIssueFlow({ open, onClose }: ReportIssueFlowProps) {
  const toast = useToast();
  const { userId } = useUser();
  const [topic, setTopic] = useState<Topic>("Bug");
  const [description, setDescription] = useState("");
  const [screenshots, setScreenshots] = useState<{ file: File; preview: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  useBodyScrollLock(open);

  const reset = useCallback(() => {
    setTopic("Bug");
    setDescription("");
    screenshots.forEach(s => URL.revokeObjectURL(s.preview));
    setScreenshots([]);
  }, [screenshots]);

  const close = useCallback(() => {
    if (submitting) return;
    reset();
    onClose();
  }, [submitting, reset, onClose]);

  const addFiles = (files: FileList | null) => {
    if (!files) return;
    const remaining = MAX_SCREENSHOTS - screenshots.length;
    const accepted: { file: File; preview: string }[] = [];
    Array.from(files).slice(0, remaining).forEach(f => {
      if (!f.type.startsWith("image/")) {
        toast.error(`${f.name} isn't an image`);
        return;
      }
      if (f.size > MAX_BYTES) {
        toast.error(`${f.name} is over 5 MB`);
        return;
      }
      accepted.push({ file: f, preview: URL.createObjectURL(f) });
    });
    if (accepted.length) setScreenshots(prev => [...prev, ...accepted]);
  };

  const removeScreenshot = (idx: number) => {
    setScreenshots(prev => {
      const next = prev.filter((_, i) => i !== idx);
      URL.revokeObjectURL(prev[idx].preview);
      return next;
    });
  };

  const submit = async () => {
    if (!userId) {
      toast.error("Please sign in to report an issue.");
      return;
    }
    if (!description.trim()) {
      toast.warn("Describe what happened first.");
      return;
    }
    setSubmitting(true);
    try {
      const urls = await Promise.all(
        screenshots.map(s => uploadScreenshot(userId, s.file).catch(err => {
          toast.error(`Screenshot upload failed: ${err?.message || "unknown"}`);
          return null;
        })),
      );
      const screenshot_urls = urls.filter((u): u is string => typeof u === "string");
      await submitIssueReport({
        user_id: userId,
        topic,
        description: description.trim(),
        screenshot_urls,
      });
      toast.success("Thanks — we'll take a look.");
      reset();
      onClose();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Failed to submit. Please try again.");
    } finally {
      setSubmitting(false);
    }
  };

  if (!open) return null;

  return (
    <div
      style={{
        position: "fixed",
        inset: 0,
        background: "rgba(0,0,0,0.4)",
        zIndex: 100,
        display: "flex",
        alignItems: "center",
        justifyContent: "center",
      }}
      onClick={close}
    >
      <div
        onClick={e => e.stopPropagation()}
        style={{
          width: 480,
          maxWidth: "calc(100vw - 32px)",
          maxHeight: "calc(100vh - 64px)",
          overflowY: "auto",
          background: "var(--bg-panel)",
          borderRadius: "var(--r-lg)",
          padding: 28,
          boxShadow: "var(--shadow-lg)",
        }}
      >
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 16 }}>
          <div className="h-serif" style={{ fontSize: 22 }}>Report an issue</div>
          <button className="btn btn--ghost btn--sm" onClick={close} aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        <div className="label-micro" style={{ marginBottom: 6 }}>Type</div>
        <div style={{ display: "flex", gap: 6, marginBottom: 16, flexWrap: "wrap" }}>
          {TOPICS.map(t => (
            <Pill key={t} active={t === topic} onClick={() => setTopic(t)}>{t}</Pill>
          ))}
        </div>

        <div className="label-micro" style={{ marginBottom: 6 }}>What happened?</div>
        <textarea
          value={description}
          onChange={e => setDescription(e.target.value)}
          placeholder="Describe the issue…"
          rows={4}
          style={{
            width: "100%",
            padding: "10px 14px",
            border: "1px solid var(--border)",
            borderRadius: "var(--r-sm)",
            fontSize: 13,
            fontFamily: "inherit",
            background: "var(--bg-input)",
            resize: "vertical",
          }}
        />

        <div className="label-micro" style={{ marginTop: 16, marginBottom: 6 }}>
          Screenshots (up to {MAX_SCREENSHOTS})
        </div>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          {screenshots.map((s, i) => (
            <div
              key={i}
              style={{
                position: "relative",
                width: 64,
                height: 64,
                borderRadius: "var(--r-sm)",
                overflow: "hidden",
                border: "1px solid var(--border)",
              }}
            >
              <img src={s.preview} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
              <button
                onClick={() => removeScreenshot(i)}
                aria-label="Remove screenshot"
                style={{
                  position: "absolute",
                  top: 2,
                  right: 2,
                  background: "rgba(0,0,0,0.6)",
                  color: "#fff",
                  width: 18,
                  height: 18,
                  borderRadius: "50%",
                  fontSize: 11,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  lineHeight: 1,
                }}
              >
                ×
              </button>
            </div>
          ))}
          {screenshots.length < MAX_SCREENSHOTS && (
            <button
              onClick={() => fileInputRef.current?.click()}
              style={{
                width: 64,
                height: 64,
                borderRadius: "var(--r-sm)",
                border: "1px dashed var(--border-strong)",
                color: "var(--text-muted)",
                fontSize: 24,
                background: "var(--bg-subtle)",
              }}
              aria-label="Add screenshot"
            >
              +
            </button>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept="image/*"
            multiple
            hidden
            onChange={e => { addFiles(e.target.files); e.target.value = ""; }}
          />
        </div>

        <div
          style={{
            marginTop: 14,
            padding: "10px 12px",
            background: "var(--bg-subtle)",
            borderRadius: "var(--r-sm)",
            fontSize: 11,
            color: "var(--text-muted)",
          }}
        >
          Your report will include the topic, your description, and any screenshots you attach.
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 16, justifyContent: "flex-end" }}>
          <button className="btn" onClick={close} disabled={submitting}>Cancel</button>
          <button className="btn btn--primary" onClick={submit} disabled={submitting}>
            {submitting ? "Submitting…" : "Submit"}
          </button>
        </div>
      </div>
    </div>
  );
}
