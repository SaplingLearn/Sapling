"use client";

import React, { Suspense, useEffect, useMemo, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { TopBar } from "../TopBar";
import { AIDisclaimerChip } from "../AIDisclaimerChip";
import { DisclaimerModal } from "../DisclaimerModal";
import { QuizPanel } from "../QuizPanel";
import { useUser } from "@/context/UserContext";
import { getCourses, getGraph, type EnrolledCourse } from "@/lib/api";
import type { GraphNode as ApiNode } from "@/lib/types";

type Concept = { id: string; name: string; course_id: string | null; course_code: string | null };

export function Quiz() {
  return (
    <Suspense fallback={<div style={{ padding: 40, color: "var(--text-dim)" }}>Loading…</div>}>
      <QuizInner />
    </Suspense>
  );
}

function QuizInner() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { userId, userReady } = useUser();

  const [concepts, setConcepts] = useState<Concept[]>([]);
  const [, setCourses] = useState<EnrolledCourse[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    if (!userReady || !userId) return;
    let cancelled = false;
    (async () => {
      try {
        const [cRes, gRes] = await Promise.all([
          getCourses(userId).catch(() => ({ courses: [] as EnrolledCourse[] })),
          getGraph(userId).catch(() => ({ nodes: [] as ApiNode[], edges: [], stats: {} })),
        ]);
        if (cancelled) return;
        setCourses(cRes.courses ?? []);
        const courseById = new Map((cRes.courses ?? []).map(c => [c.course_id, c]));
        const nodes = (gRes.nodes ?? []) as ApiNode[];
        setConcepts(
          nodes
            .filter(n => !n.is_subject_root)
            .map(n => ({
              id: n.id,
              name: n.concept_name || "Concept",
              course_id: n.course_id ?? null,
              course_code: n.course_id ? (courseById.get(n.course_id)?.course_code ?? null) : null,
            })),
        );
      } catch (err) {
        console.error("quiz bootstrap failed", err);
      } finally {
        if (!cancelled) setLoaded(true);
      }
    })();
    return () => { cancelled = true; };
  }, [userReady, userId]);

  const topicParam = searchParams.get("topic");
  const conceptParam = searchParams.get("concept");

  const initialConceptId = useMemo(() => {
    if (conceptParam) return conceptParam;
    if (!topicParam) return null;
    const t = topicParam.trim().toLowerCase();
    return concepts.find(c => c.name.toLowerCase() === t)?.id ?? null;
  }, [conceptParam, topicParam, concepts]);

  return (
    <div style={{ display: "flex", height: "100vh", flexDirection: "column" }}>
      <DisclaimerModal />
      <TopBar
        title="Quiz"
        subtitle="Pick a concept and test what you know."
        actions={<AIDisclaimerChip />}
      />
      <div
        style={{
          padding: "40px 48px 64px",
          flex: 1,
          overflowY: "auto",
          display: "flex",
          justifyContent: "center",
          alignItems: "flex-start",
        }}
      >
        {!userReady ? null : !userId ? (
          <div style={{ fontSize: 13, color: "var(--text-muted)" }}>Sign in to take a quiz.</div>
        ) : loaded ? (
          <QuizPanel
            userId={userId}
            concepts={concepts}
            initialConceptId={initialConceptId}
            onExit={() => router.push("/learn")}
          />
        ) : null}
      </div>
    </div>
  );
}
