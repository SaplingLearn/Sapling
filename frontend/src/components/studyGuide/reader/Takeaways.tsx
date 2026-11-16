import { SkeletonText } from "@/components/Skeleton";

import s from "./reader.module.css";

/** The few things to remember. They arrive with the outline. */
export function Takeaways({ takeaways, generating }: { takeaways: string[]; generating: boolean }) {
  if (takeaways.length === 0 && !generating) return null;
  return (
    <section aria-label="Key takeaways" className={s.takeaways}>
      <span className="label-micro">
        {takeaways.length === 3 ? "If you only remember three things" : "Key takeaways"}
      </span>
      {takeaways.length === 0 ? (
        <SkeletonText lines={3} lineHeight={16} gap={14} lastWidth="88%" />
      ) : (
        <ol className={s.takeawayList}>
          {takeaways.map((takeaway, i) => (
            <li key={i}>
              <span className={s.takeawayNumber}>{i + 1}</span>
              <span>{takeaway}</span>
            </li>
          ))}
        </ol>
      )}
    </section>
  );
}
