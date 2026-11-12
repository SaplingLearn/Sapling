import Link from "next/link";

import type { EnrolledCourse } from "@/lib/api";
import type { GuideCard } from "@/lib/studyGuide/types";
import { studyGuideReaderHref } from "@/lib/toolHrefs";

import { classColor } from "../shared/classColor";
import { ClassTag } from "../shared/ClassTag";
import { Pill } from "../shared/Pill";
import s from "./home.module.css";

/**
 * The study guides saved to the Library, as their own short section over the
 * documents: the home's card, down to its title and last row. Each opens in
 * the reader. Nothing is rendered when there are none.
 */
export function LibraryGuides({ guides, courses }: { guides: GuideCard[]; courses: EnrolledCourse[] }) {
  if (guides.length === 0) return null;
  return (
    <section className={s.librarySection} aria-label="Saved study guides">
      <span className="label-micro">Study guides</span>
      <ul className={s.libraryGrid}>
        {guides.map(guide => (
          <li key={guide.id} className={s.cell}>
            <Link
              href={studyGuideReaderHref(guide.id)}
              className={`${s.card} ${s.short}`}
              data-testid={`library-guide-${guide.id}`}
            >
              <h3 className={s.title} title={guide.title}>{guide.title}</h3>
              <div className={s.foot}>
                <span className={s.pills}>
                  <Pill>{guide.scope_label}</Pill>
                  <Pill>Study guide</Pill>
                </span>
                <ClassTag
                  code={guide.course_code}
                  name={guide.course_name}
                  color={classColor(courses, guide.course_id)}
                />
              </div>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
