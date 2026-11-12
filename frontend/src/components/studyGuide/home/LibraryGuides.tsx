import Link from "next/link";

import { Chip } from "@/components/ui";
import type { GuideCard } from "@/lib/studyGuide/types";
import { studyGuideReaderHref } from "@/lib/toolHrefs";

import s from "./home.module.css";

/**
 * The study guides saved to the Library, as their own short section over the
 * documents. Each opens in the reader. Nothing is rendered when there are none.
 */
export function LibraryGuides({ guides }: { guides: GuideCard[] }) {
  if (guides.length === 0) return null;
  return (
    <section className={s.librarySection} aria-label="Saved study guides">
      <span className="label-micro">Study guides</span>
      <ul className={s.libraryGrid}>
        {guides.map(guide => (
          <li key={guide.id} className={s.cell}>
            <Link
              href={studyGuideReaderHref(guide.id)}
              className={`${s.card} ${s.libraryCard}`}
              data-testid={`library-guide-${guide.id}`}
            >
              <span className={`h-serif ${s.title}`}>{guide.title}</span>
              <span className={s.foot}>
                <Chip variant="accent">Study guide</Chip>
                <span className={s.course}>{guide.course_name}</span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
