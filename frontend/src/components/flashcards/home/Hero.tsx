"use client";
/**
 * The home's lead: one olive block that asks what the student wants to study.
 *
 * The field is "describe a set": the student says it in their own words
 * ("pointers and recursion for the midterm"), the server answers with the
 * course concepts that fit and a name, and the ones on this course's map are
 * handed to the page, which opens the builder with them ticked. Nothing is
 * saved by describing. When nothing matched the student stays here and is
 * told so under the field.
 *
 * The chips under the field are examples made from the course's own data; tapping one
 * fills the field (it does not submit). On the right, three figures.
 */
import React from "react";
import { useUser } from "@/context/UserContext";
import { humanizeError } from "@/lib/errorMessage";
import { SUGGEST_MAX, SUGGEST_MIN, suggestFlashcardSet } from "@/lib/flashcardSetsApi";
import { useLatestRequest } from "@/lib/useLatestRequest";
import { Icon } from "../../Icon";
import { useToast } from "../../ToastProvider";
import { describeNote, namesOnMap, type MapColumn } from "./flashcardsModel";
import h from "./home.module.css";

export interface HeroFigures {
  cards: number;
  concepts: number;
  sets: number;
}

export interface HeroProps {
  courseId: string;
  columns: MapColumn[];
  /** False when there is nothing to sort a description into (no course, or
   *  a course with no concepts yet). */
  canSort: boolean;
  examples: string[];
  /** null while they load. */
  figures: HeroFigures | null;
  /** The described concepts that are on the map, the suggested name, and the
   *  line that says what the sort did. */
  onSorted: (names: string[], name: string, note: string) => void;
}

export function Hero({ courseId, columns, canSort, examples, figures, onSorted }: HeroProps) {
  const toast = useToast();
  const { userId } = useUser();
  const [text, setText] = React.useState("");
  const [sorting, setSorting] = React.useState(false);
  /** Why the last sort went nowhere. */
  const [note, setNote] = React.useState("");
  const input = React.useRef<HTMLInputElement | null>(null);
  const req = useLatestRequest();
  // The answer is matched against the map as it is when the answer lands.
  const map = React.useRef(columns);
  React.useEffect(() => { map.current = columns; });

  const description = text.trim().slice(0, SUGGEST_MAX);
  const ready = canSort && description.length >= SUGGEST_MIN && !sorting;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!ready) return;
    const run = req.begin();
    setSorting(true);
    setNote("");
    try {
      const r = await suggestFlashcardSet(userId, description, courseId);
      if (!run.isCurrent()) return;
      const { found } = namesOnMap((r.concepts || []).map(c => c.name), map.current);
      const said = describeNote(found.length, r.considered || 0);
      if (found.length) onSorted(found, r.name || "", said);
      else setNote(said);
    } catch (err) {
      if (!run.isCurrent()) return;
      console.error("flashcard set suggest failed", err);
      toast.error(humanizeError(err, "Couldn't sort that into a set. Try again."));
    } finally {
      if (run.isCurrent()) setSorting(false);
    }
  };

  const tryIt = (example: string) => {
    setText(example);
    input.current?.focus();
  };

  return (
    <section className={h.hero} aria-labelledby="flashcards-hero-title">
      <div className={h.heroMain}>
        <h2 id="flashcards-hero-title" className={`h-serif ${h.heroTitle}`}>What do you want to study?</h2>
        <form className={h.prompt} onSubmit={submit}>
          <input
            ref={input}
            className={h.promptField}
            aria-label="Describe a set"
            placeholder={canSort || !figures ? "e.g. pointers and the recursion stuff for the midterm" : "Nothing to sort yet: this needs a course with concepts"}
            value={text}
            maxLength={SUGGEST_MAX}
            autoComplete="off"
            disabled={!canSort}
            onChange={e => setText(e.target.value)}
          />
          <button type="submit" className={h.promptGo} disabled={!ready}>
            <Icon name="sparkle" size={14} /> {sorting ? "Sorting…" : "Sort it"}
          </button>
        </form>
        {canSort && examples.length > 0 && (
          <div className={h.ideas} role="group" aria-label="Examples">
            {examples.map(example => (
              <button key={example} type="button" className={h.idea} onClick={() => tryIt(example)}>{example}</button>
            ))}
          </div>
        )}
        <p className={h.heroNote} role="status">{note}</p>
      </div>
      <dl className={h.stats} aria-busy={figures ? undefined : true}>
        {(["cards", "concepts", "sets"] as const).map(kind => (
          <div key={kind} className={h.stat} data-testid={`flashcards-figure-${kind}`}>
            {/* Label first for a reader; the stylesheet puts the figure on top. */}
            <dt className={h.statLabel}>{kind}</dt>
            <dd className={`h-serif ${h.statFigure}`}>{figures ? figures[kind] : "–"}</dd>
          </div>
        ))}
      </dl>
    </section>
  );
}
