"use client";
import { motion } from "framer-motion";
import { Icon } from "../Icon";
import { useMotionPresets } from "@/lib/motion";
import styles from "./LearnNextCard.module.css";
import { useUser } from "@/context/UserContext";
import { useLoopStatus } from "@/components/learn/useLoopStatus";
import { learnHrefForNode } from "@/lib/data";

/** One Learn-next row: graph `/recommendations` (flag-off) or a learner-next
 *  concept from `GET /api/study/{id}/next` (W8.7; learning_loop +
 *  quiz_concept_plan). `node_id` and `course_id` name the concept (#866 K05);
 *  an older server / legacy row may send neither. */
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
  const m = useMotionPresets();
  return (
    <div className={`card ${styles.card}`} data-testid="dashboard-learn-next">
      <div className={styles.header}>
        <div className="label-micro">Learn next</div>
        <button className="btn btn--ghost btn--sm" data-testid="dashboard-learn-next-tree" onClick={() => navigate("/tree")}>Tree →</button>
      </div>
      {recommendations.length === 0 && (
        <div className={styles.empty}>Nothing suggested yet — start a session.</div>
      )}
      {/* The recommendations arrive after the dashboard's first paint: they
          stagger in, so the student sees the list land. */}
      <motion.div variants={m.list.container} initial="hidden" animate="shown">
        {recommendations.slice(0, 3).map((r, i) => (
          <motion.button
            key={`${r.concept_name}-${i}`}
            variants={m.list.item}
            data-testid="dashboard-learn-next-item"
            data-node-id={r.node_id ?? undefined}
            onClick={() => navigate(recommendationHref(r, loop === true))}
            className={styles.item}
          >
            <Icon name="sparkle" size={14} />
            <div className={styles.itemText}>
              <div className={styles.itemTitle}>{r.concept_name}</div>
              {r.reason && <div className={styles.itemReason}>{r.reason}</div>}
            </div>
            <Icon name="chev" size={12} />
          </motion.button>
        ))}
      </motion.div>
      <div className={styles.footer}>
        <button className={`btn btn--sm ${styles.footerBtn}`} data-testid="dashboard-study-room" onClick={() => navigate("/social")}>
          <Icon name="users" size={12} /> Study room
        </button>
      </div>
    </div>
  );
}
