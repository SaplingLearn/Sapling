"use client";
import { Icon } from "../Icon";
import { useUser } from "@/context/UserContext";
import { useLoopStatus } from "@/components/learn/useLoopStatus";
import { learnHrefForNode } from "@/lib/data";

/** One GET /api/graph/{user}/recommendations entry. `node_id` and `course_id`
 *  name the concept (#866 K05); an older server sends neither. */
export type Recommendation = { concept_name: string; reason?: string; node_id?: string | null; course_id?: string | null };

/** Where a Learn next recommendation opens the Tutor. With the learning loop on
 *  for the student, the concept's own link (as the map's Learn link): the
 *  loop's session starts on that concept, never on the whole course. Otherwise
 *  (the loop off, its status not known yet, or an older server) main's link,
 *  byte for byte: the legacy Learn screen is unchanged. */
export function recommendationHref(r: Recommendation, loopOn: boolean): string {
  if (loopOn && r.node_id && r.course_id) {
    return learnHrefForNode({ id: r.node_id, name: r.concept_name, course_id: r.course_id, is_subject_root: false });
  }
  return `/learn?topic=${encodeURIComponent(r.concept_name)}&mode=socratic`;
}

/** The legacy right panel's Learn next card: up to three recommendations, the
 *  map, and the study room. The loop status is read only when a recommendation
 *  names a concept (a flag-off student reads none: useLoopStatus). */
export function LearnNextCard({ recommendations, navigate }: {
  recommendations: Recommendation[];
  navigate: (href: string) => void;
}) {
  const { userId, userReady } = useUser();
  const named = recommendations.some((r) => r.node_id && r.course_id);
  const { status: loop } = useLoopStatus(userId, userReady && named);
  return (
    <div className="card" style={{ padding: "var(--pad-lg)" }} data-testid="dashboard-learn-next">
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12 }}>
        <div className="label-micro">Learn next</div>
        <button className="btn btn--ghost btn--sm" data-testid="dashboard-learn-next-tree" onClick={() => navigate("/tree")}>Tree →</button>
      </div>
      {recommendations.length === 0 && (
        <div style={{ fontSize: 12, color: "var(--text-muted)" }}>Nothing suggested yet — start a session.</div>
      )}
      {recommendations.slice(0, 3).map((r, i) => (
        <button
          key={`${r.concept_name}-${i}`}
          data-testid="dashboard-learn-next-item"
          data-node-id={r.node_id ?? undefined}
          onClick={() => navigate(recommendationHref(r, loop === true))}
          style={{
            display: "flex", alignItems: "flex-start", gap: 10, width: "100%",
            padding: "10px 12px", borderRadius: "var(--r-md)",
            background: "var(--bg-subtle)", marginBottom: 6, textAlign: "left",
          }}
        >
          <Icon name="sparkle" size={14} />
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{r.concept_name}</div>
            {r.reason && <div style={{ fontSize: 11, color: "var(--text-muted)" }}>{r.reason}</div>}
          </div>
          <Icon name="chev" size={12} />
        </button>
      ))}
      <div style={{ display: "flex", gap: 6, marginTop: 10 }}>
        <button className="btn btn--sm" style={{ flex: 1 }} data-testid="dashboard-study-room" onClick={() => navigate("/social")}>
          <Icon name="users" size={12} /> Study room
        </button>
      </div>
    </div>
  );
}
