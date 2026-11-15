"use client";
/**
 * The Flashcards HOME: say what you want to study, or pick a deck.
 *
 * Top to bottom: the hero (the prompt, example prompts, three figures), then
 * "Your sets" as a grid of decks: what is due, everything in the course, each
 * saved set, and a tile to build one by hand. Ticking decks brings up the mix
 * bar. There is no concept grid here: that is the builder (SetBuilder), a step
 * the student enters on purpose, and every way into it goes through the
 * page's `onBuild`.
 */
import React from "react";
import Link from "next/link";
import type { FlashcardSet } from "@/lib/flashcardSetsApi";
import type { ChecklistTopic } from "@/lib/topicChecklistApi";
import { useIsNavHidden } from "@/lib/useNavHidden";
import type { Concept } from "../../study/studyModel";
import { DeckGrid, MixBar } from "./Decks";
import {
  buildDecks,
  examplePrompts,
  firstUnit,
  mixOf,
  mixable,
  nextExam,
  type Deck,
} from "./decksModel";
import { namesOnMap, orderNames, type DraftAction, type ExamRef, type HomeModel } from "./flashcardsModel";
import h from "./home.module.css";
import { Hero } from "./Hero";
import type { SetsState } from "./useFlashcardsData";
import { useSetActions } from "./useSetActions";
import { startStatus, type StartPlan, type StartProgress } from "./useStart";

/** New cards per concept when a deck is played from the home (the builder's default). */
const PER_CONCEPT = 5;

export interface FlashcardsHomeProps {
  courseLabel: string;
  /** "" for a student with no course. */
  courseId: string;
  concepts: Concept[];
  /** The course's outline: whether the map's columns are its own units. */
  outline: ChecklistTopic[];
  model: HomeModel;
  exams: ExamRef[];
  today: Date;
  sets: SetsState;
  dispatch: React.Dispatch<DraftAction>;
  progress: StartProgress | null;
  running: boolean;
  /** Why the last play started nothing. */
  notice: string | null;
  /** The deck a review is being started from. */
  playing: string | null;
  /** Starts a review; `deckId` is the deck it was asked from, if one. */
  onPlay: (plan: StartPlan, deckId: string | null) => void;
  onPlayDue: () => void;
  /** Opens the builder on the draft as it now is; `note`: what a sort did. */
  onBuild: (note?: string) => void;
}

export function FlashcardsHome(props: FlashcardsHomeProps) {
  const { model, sets, dispatch, concepts, courseLabel } = props;
  const actions = useSetActions(sets, model.columns, props.exams, dispatch);
  const decks = React.useMemo(
    () => buildDecks({ sets: sets.sets, model, concepts, exams: props.exams, courseLabel, today: props.today }),
    [sets.sets, model, concepts, props.exams, courseLabel, props.today],
  );
  const examples = React.useMemo(
    () => examplePrompts({ exam: nextExam(props.exams, props.today), concepts, unit: firstUnit(concepts, props.outline) }),
    [props.exams, props.today, concepts, props.outline],
  );

  // Ticked decks, by id; one that is gone (a deleted set) is simply not found.
  const [tickedIds, setTickedIds] = React.useState<string[]>([]);
  const ticked = decks.filter(deck => tickedIds.includes(deck.id));
  const mix = mixOf(ticked, model);
  const tick = (deck: Deck) =>
    setTickedIds(ids => (ids.includes(deck.id) ? ids.filter(id => id !== deck.id) : [...ids, deck.id]));

  const hasCourse = !!props.courseId;
  // Something on the map to make a set of: the course's concepts, or decks.
  const hasMap = model.columns.length > 0;

  const play = (deck: Deck) => {
    if (deck.kind === "due") { props.onPlayDue(); return; }
    props.onPlay({
      names: orderNames(deck.names, model.columns),
      generate: deck.generate,
      onlyDue: deck.onlyDue,
      shuffle: deck.shuffle,
      perConcept: PER_CONCEPT,
      title: deck.name,
    }, deck.id);
  };

  /** The union of the ticked decks' concepts, shuffled. */
  const studyTogether = () => {
    if (ticked.length === 1) { play(ticked[0]); return; }
    props.onPlay({
      names: mix.names, generate: mix.generate, onlyDue: false, shuffle: true,
      perConcept: PER_CONCEPT, title: `${ticked.length} sets together`,
    }, null);
  };

  // Every way into the builder starts from a clean draft.
  const buildByHand = () => {
    dispatch({ type: "reset" });
    props.onBuild();
  };
  const open = (set: FlashcardSet) => {
    if (actions.load(set)) props.onBuild();
  };
  /** The union ticked, no name, no set attached: theirs to name and save. */
  const merge = () => {
    dispatch({ type: "reset" });
    dispatch({ type: "many", names: mix.names, on: true, custom: namesOnMap(mix.names, model.columns).missing });
    props.onBuild();
  };
  const sorted = (names: string[], name: string, note: string) => {
    dispatch({ type: "reset" });
    dispatch({ type: "describe", names, name });
    props.onBuild(note);
  };

  return (
    <div className={h.home}>
      <Hero
        courseId={props.courseId}
        columns={model.columns}
        canSort={hasCourse && concepts.length > 0}
        examples={examples}
        figures={{ cards: model.courseCards.length, concepts: model.columns.reduce((n, col) => n + col.items.length, 0), sets: (sets.sets ?? []).length }}
        onSorted={sorted}
      />

      {concepts.length === 0 && <NoConcepts hasCourse={hasCourse} />}

      {(decks.length > 0 || hasMap) && (
        <section className={h.sets} aria-label="Your sets">
          <div className={h.setsHead}>
            <span className="label-micro">Your sets</span>
            {decks.filter(mixable).length >= 2 && <span className={h.setsHint}>Tick sets to study them together</span>}
          </div>
          <DeckGrid
            decks={decks}
            ticked={tickedIds}
            playing={props.playing}
            busy={props.running}
            canBuild={hasMap}
            onPlay={play}
            onOpen={open}
            onTick={tick}
            onRename={actions.rename}
            onDelete={set => { void actions.remove(set); }}
            onBuild={buildByHand}
          />
          {/* Which concept is being made, or why nothing started. Its line is
              always there, so it moves nothing. */}
          <p className={h.deckStatus} role="status" data-testid="flashcards-home-status">
            {startStatus(props.progress, props.running, props.notice)}
          </p>
        </section>
      )}

      {ticked.length > 0 && (
        <MixBar
          sets={ticked.length}
          cards={mix.cards}
          busy={props.running}
          onStudy={studyTogether}
          onMerge={ticked.length > 1 ? merge : undefined}
          onClear={() => setTickedIds([])}
        />
      )}
    </div>
  );
}

/** Nothing to make a set of yet, and where the concepts come from. The way
 *  there is the Library; a student it is hidden from (`hide_library`) is told
 *  the same without a link that would only land on the Dashboard. */
function NoConcepts({ hasCourse }: { hasCourse: boolean }) {
  const libraryHidden = useIsNavHidden()("/library");
  const library = libraryHidden ? null : <Link href="/library">Library</Link>;
  return (
    <p className={h.quiet} style={{ marginTop: 20 }} data-testid="flashcards-no-concepts">
      {hasCourse
        ? library
          ? <>No concepts for this course yet. Upload its material in the {library} and you can make sets of them here.</>
          : <>No concepts for this course yet. Once its material is uploaded you can make sets of them here.</>
        : library
          ? <>Add a course to make flashcards for it. Material you upload in the {library} becomes the concepts your sets are made of.</>
          : <>Add a course to make flashcards for it. Its material becomes the concepts your sets are made of.</>}
    </p>
  );
}

/** The home's shape while its data loads: the hero with blank figures, then
 *  deck-sized placeholders. */
export function FlashcardsHomeSkeleton() {
  return (
    <div className={h.home} aria-busy="true" aria-label="Loading flashcards" data-testid="flashcards-home-loading">
      <Hero courseId="" columns={[]} canSort={false} examples={[]} figures={null} onSorted={() => {}} />
      <div className={h.sets}>
        <div className={h.setsHead}><span className="label-micro">Your sets</span></div>
        <ul className={h.decks} aria-hidden="true">
          {[0, 1, 2, 3].map(i => <li key={i} className={`${h.deck} ${h.deckGhost} skeleton`} />)}
        </ul>
      </div>
    </div>
  );
}
