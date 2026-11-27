"use client";

import React, { useCallback, useRef, useState } from "react";
import { Icon } from "./Icon";
import { Pill } from "./Pill";
import { useToast } from "./ToastProvider";
import { useUser } from "@/context/UserContext";
import Dialog from "@/components/Dialog";
import { submitIssueReport, API_URL } from "@/lib/api";
import { LONG_TEXT_MAX } from "@/lib/inputLimits";

const TOPICS = ["Bug", "Feature", "Polish", "Content", "Other"] as const;
type Topic = typeof TOPICS[number];

const MAX_SCREENSHOTS = 5;
const MAX_BYTES = 5 * 1024 * 1024;

interface ReportIssueFlowProps {
  open: boolean;
  onClose: () => void;
}

// #231: upload via the auth-gated backend endpoint (service-role) instead of the
// public anon storage client, so issues-media-files can be made private. Returns
// the storage path (stored in screenshot_urls), not a public URL.
async function uploadScreenshot(file: File): Promise<string> {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${API_URL}/api/issue-reports/screenshot`, {
    method: "POST",
    credentials: "include",
    body: form,
  });
  if (!res.ok) throw new Error(`Screenshot upload failed (${res.status})`);
  const data = (await res.json()) as { path: string };
  return data.path;
}

export function ReportIssueFlow({ open, onClose }: ReportIssueFlowProps) {
  const toast = useToast();
  const { userId } = useUser();
  const [topic, setTopic] = useState<Topic>("Bug");
  const [description, setDescription] = useState("");
  const [screenshots, setScreenshots] = useState<{ file: File; preview: string }[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);


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
        screenshots.map(s => uploadScreenshot(s.file).catch(err => {
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

  return (
    <Dialog open={open} onClose={close} labelledBy="report-issue-title" width="480px" showCloseButton={false}>
        <div className="flex justify-between items-center mb-4">
          <div id="report-issue-title" className="h-serif text-2xl">Report an issue</div>
          <button className="btn btn--ghost btn--sm" onClick={close} aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </div>

        <div className="label-micro mb-1.5">Type</div>
        <div className="flex gap-1.5 mb-4 flex-wrap">
          {TOPICS.map(t => (
            <Pill key={t} active={t === topic} onClick={() => setTopic(t)}>{t}</Pill>
          ))}
        </div>

        <div className="label-micro mb-1.5">What happened?</div>
        <textarea
          value={description}
          maxLength={LONG_TEXT_MAX}
          onChange={e => setDescription(e.target.value)}
          placeholder="Describe the issue…"
          rows={4}
          className="w-full py-2.5 px-3.5 border border-border rounded-sm text-md [font-family:inherit] bg-bg-input resize-y"
        />

        <div className="label-micro mt-4 mb-1.5">
          Screenshots (up to {MAX_SCREENSHOTS})
        </div>
        <div className="flex gap-2 flex-wrap">
          {screenshots.map((s, i) => (
            <div
              key={i}
              className="relative w-16 h-16 rounded-sm overflow-hidden border border-border"
            >
              <img src={s.preview} alt="" className="w-full h-full object-cover" />
              <button
                onClick={() => removeScreenshot(i)}
                aria-label="Remove screenshot"
                className="absolute top-0.5 right-0.5 bg-[rgba(0,0,0,0.6)] text-accent-fg w-4.5 h-4.5 rounded-[50%] text-xs flex items-center justify-center leading-none"
              >
                ×
              </button>
            </div>
          ))}
          {screenshots.length < MAX_SCREENSHOTS && (
            <button
              onClick={() => fileInputRef.current?.click()}
              className="w-16 h-16 rounded-sm border border-dashed border-border-strong text-text-muted text-[24px] bg-bg-subtle"
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
          className="mt-3.5 py-2.5 px-3 bg-bg-subtle rounded-sm text-xs text-text-muted"
        >
          Your report will include the topic, your description, and any screenshots you attach.
        </div>

        <div className="flex gap-2 mt-4 justify-end">
          <button className="btn" onClick={close} disabled={submitting}>Cancel</button>
          <button className="btn btn--primary" onClick={submit} disabled={submitting}>
            {submitting ? "Submitting…" : "Submit"}
          </button>
        </div>
    </Dialog>
  );
}
