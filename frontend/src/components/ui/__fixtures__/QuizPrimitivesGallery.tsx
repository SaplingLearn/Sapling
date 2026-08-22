"use client";

/**
 * QuizPrimitivesGallery — every primitive, every state, on one page (#537).
 *
 * A harness, not a route and not a test: it exists so the shared primitives
 * can be looked at in isolation at the shell's real content width before any
 * screen consumes them, and so a design review has something to screenshot.
 * Mount it anywhere (a scratch route, a story, a Playwright fixture page) —
 * it takes no data and touches nothing.
 *
 * Light mode only: the app has no dark mode, deliberately (globals.css).
 *
 * `--quiz-accent` is set on the root here exactly as `QuizScreen` will set it
 * from the active concept's course colour, so the accent-derived states
 * (segmented underline, selection bar, progress dots, banner tint) render the
 * way they will in the real screen rather than in the app's default green.
 */

import React from "react";
import { ConceptNode } from "@/components/graph/ConceptNode";
import { ConceptNeighbourhood } from "@/components/graph/ConceptNeighbourhood";
import type { NeighbourNode } from "@/lib/graph/neighbourhood";
import { AnswerOption, type AnswerState } from "../AnswerOption";
import { Button } from "../Button";
import { EmptyState } from "../EmptyState";
import { InlineBanner } from "../InlineBanner";
import { ProgressDots } from "../ProgressDots";
import { SegmentedControl } from "../SegmentedControl";
import { Sheet } from "../Sheet";

/** The prototype's CS101 purple, so the gallery matches the design's screens. */
const COURSE_COLOR = "#7b4b99";

const CENTRE = { id: "recursion", name: "Recursion", mastery: 0.29, tier: "struggling" };

const SIBLINGS: NeighbourNode[] = [
  { id: "base-cases", name: "Base cases", mastery: 0.52, tier: "learning", strength: 0.9 },
  { id: "stack-frames", name: "Stack frames", mastery: 0.3, tier: "struggling", strength: 0.7 },
  { id: "tail-recursion", name: "Tail recursion", mastery: 0.12, tier: "struggling", strength: 0.4 },
];

const ANSWER_STATES: AnswerState[] = [
  "default",
  "selected",
  "correct",
  "chosen-wrong",
  "muted",
];

const ANSWER_TEXT: Record<AnswerState, string> = {
  default: "It makes the function run faster by caching the results of earlier calls",
  selected: "It stops the recursion by returning a result without another recursive call",
  correct: "It stops the recursion by returning a result without another recursive call",
  "chosen-wrong": "It increases the recursion depth available on the call stack",
  muted: "It converts the recursion into an iterative loop at compile time",
};

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="quiz-gallery__section">
      <h2 className="quiz-gallery__heading label-micro">{title}</h2>
      {children}
    </section>
  );
}

function Row({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="quiz-gallery__row">
      <span className="quiz-gallery__caption">{label}</span>
      <div className="quiz-gallery__specimens">{children}</div>
    </div>
  );
}

export function QuizPrimitivesGallery() {
  const [count, setCount] = React.useState(5);
  const [difficulty, setDifficulty] = React.useState("medium");
  const [feedback, setFeedback] = React.useState("at-end");
  const [picked, setPicked] = React.useState<string | null>("B");
  const [sheetOpen, setSheetOpen] = React.useState(false);

  return (
    <div
      className="quiz-gallery"
      style={{ "--quiz-accent": COURSE_COLOR } as React.CSSProperties}
    >
      <h1 className="h-serif quiz-gallery__title">Quiz primitives</h1>

      <Section title="Button">
        <Row label="variants">
          <Button variant="primary">Start</Button>
          <Button>Leave</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="danger">Discard attempt</Button>
          <Button variant="link">adjust</Button>
          <Button variant="link" aria-pressed data-active="true">
            adjust (open)
          </Button>
        </Row>
        <Row label="sizes">
          <Button size="sm">sm</Button>
          <Button>md</Button>
          <Button size="lg">lg</Button>
          <Button variant="primary" size="xl">
            xl
          </Button>
        </Row>
        <Row label="disabled primary — both forms">
          {/* The DOM attribute, and the aria-only form the quiz's Submit uses
              so it stays focusable and announced while it can't be pressed. */}
          <Button variant="primary" disabled>
            Submit (disabled)
          </Button>
          <Button variant="primary" aria-disabled="true">
            Submit (aria-disabled)
          </Button>
          <Button variant="primary">Submit (enabled)</Button>
        </Row>
      </Section>

      <Section title="SegmentedControl">
        <Row label="length">
          <SegmentedControl
            options={[3, 5, 10].map((v) => ({ value: v, label: `${v} questions` }))}
            value={count}
            onChange={setCount}
            ariaLabel="Length"
            testid="gallery-seg-count"
          />
        </Row>
        <Row label="difficulty">
          <SegmentedControl
            options={["easy", "medium", "hard", "adaptive"].map((v) => ({ value: v, label: v }))}
            value={difficulty}
            onChange={setDifficulty}
            ariaLabel="Difficulty"
            testid="gallery-seg-difficulty"
          />
        </Row>
        <Row label="answers">
          <SegmentedControl
            options={[
              { value: "as-you-go", label: "as you go" },
              { value: "at-end", label: "at the end" },
            ]}
            value={feedback}
            onChange={setFeedback}
            ariaLabel="Answers"
            testid="gallery-seg-feedback"
          />
        </Row>
        <Row label="with a disabled option">
          <SegmentedControl
            options={[
              { value: "easy", label: "easy" },
              { value: "medium", label: "medium" },
              { value: "hard", label: "hard", disabled: true },
            ]}
            value="medium"
            onChange={() => {}}
            ariaLabel="Difficulty with a disabled option"
          />
        </Row>
      </Section>

      <Section title="AnswerOption — every state">
        <div className="quiz-gallery__answers" role="radiogroup" aria-label="Answer choices">
          {ANSWER_STATES.map((state, i) => (
            <AnswerOption
              key={state}
              letter={String.fromCharCode(65 + i)}
              text={ANSWER_TEXT[state]}
              state={state}
              tabIndex={i === 0 ? 0 : -1}
              onSelect={() => {}}
            />
          ))}
          <AnswerOption
            letter="F"
            text="Disabled — revealed, still readable, no longer answerable"
            state="muted"
            disabled
          />
        </div>
        <Row label="live (click to pick)">
          <div className="quiz-gallery__answers" role="radiogroup" aria-label="Pick one">
            {["A", "B", "C"].map((letter, i) => (
              <AnswerOption
                key={letter}
                letter={letter}
                text={`Option ${letter}`}
                state={picked === letter ? "selected" : "default"}
                tabIndex={picked === letter || (!picked && i === 0) ? 0 : -1}
                onSelect={() => setPicked(letter)}
              />
            ))}
          </div>
        </Row>
      </Section>

      <Section title="ProgressDots">
        <Row label="column · question 3 of 5">
          <ProgressDots total={5} current={2} answered={2} ariaLabel="Question 3 of 5" />
        </Row>
        <Row label="column · first, and last">
          <ProgressDots total={5} current={0} answered={0} ariaLabel="Question 1 of 5" />
          <ProgressDots total={5} current={4} answered={4} ariaLabel="Question 5 of 5" />
          <ProgressDots total={3} current={1} answered={1} ariaLabel="Question 2 of 3" />
        </Row>
        <Row label="row">
          <ProgressDots
            total={4}
            current={1}
            answered={1}
            orientation="row"
            ariaLabel="Step 2 of 4"
          />
        </Row>
      </Section>

      <Section title="InlineBanner">
        <InlineBanner
          actions={
            <>
              <Button>Resume</Button>
              <Button variant="link">Discard</Button>
            </>
          }
        >
          You left a quiz on Recursion — 2 of 5 answered
        </InlineBanner>
        <InlineBanner tone="neutral">
          Only 3 questions were ready for this concept.
        </InlineBanner>
      </Section>

      <Section title="Sheet">
        <Row label="right-anchored panel over the page">
          <Button onClick={() => setSheetOpen(true)}>Ask about this</Button>
        </Row>
        <Sheet
          open={sheetOpen}
          onClose={() => setSheetOpen(false)}
          title="Ask about this"
          testid="gallery-sheet"
        >
          <p className="body-serif">
            What is the purpose of a base case in a recursive function?
          </p>
          <p>You chose B · The answer is B.</p>
          <Button variant="primary" onClick={() => setSheetOpen(false)}>
            Close
          </Button>
        </Sheet>
      </Section>

      <Section title="EmptyState">
        <EmptyState
          icon="flask"
          title="Your tree is empty"
          body="Upload notes or talk to the tutor and concepts will appear here."
          action={{ label: "Go to your library", href: "/library" }}
        />
        <EmptyState
          size="hero"
          eyebrow="Spring 2026"
          title="A blank semester, ready to plant."
          body="Drop in a syllabus and Sapling lays out every assignment, due date, and weight."
          action={{ label: "Upload syllabus", href: "/gradebook" }}
        />
      </Section>

      <Section title="ConceptNode">
        <Row label="dot · 11 / 14 / 15px">
          <ConceptNode size={11} variant={{ kind: "dot" }} courseColor={COURSE_COLOR} {...marks.recursion} />
          <ConceptNode size={14} variant={{ kind: "dot" }} courseColor={COURSE_COLOR} {...marks.baseCases} />
          <ConceptNode size={15} variant={{ kind: "dot" }} courseColor={COURSE_COLOR} {...marks.recursion} />
        </Row>
        <Row label="node · 26px, with the glow">
          <ConceptNode size={26} courseColor={COURSE_COLOR} {...marks.recursion} />
          <ConceptNode size={26} courseColor={COURSE_COLOR} {...marks.baseCases} />
          <ConceptNode size={26} courseColor={COURSE_COLOR} {...marks.mastered} />
          <ConceptNode size={26} courseColor={COURSE_COLOR} {...marks.unexplored} />
        </Row>
        <Row label="course root · unshaded, flat radius">
          <ConceptNode
            size={26}
            isRoot
            nodeId="subject_root__cs101"
            mastery={0}
            tier="mastered"
            courseColor={COURSE_COLOR}
          />
        </Row>
        <Row label="with a caption, truncated at 18">
          <ConceptNode size={40} courseColor={COURSE_COLOR} {...marks.recursion} label="Recursion" />
          <ConceptNode
            size={40}
            courseColor={COURSE_COLOR}
            {...marks.baseCases}
            label="Fundamental theorem of calculus"
          />
        </Row>
        <Row label="growth · animated, then static">
          <ConceptNode
            size={96}
            courseColor={COURSE_COLOR}
            {...marks.recursion}
            variant={{ kind: "growth", before: 0.29, after: 0.46 }}
            title="Recursion node grew from 29% to 46% mastery"
          />
          <ConceptNode
            size={96}
            courseColor={COURSE_COLOR}
            {...marks.recursion}
            variant={{ kind: "growth", before: 0.29, after: 0.46 }}
            animate={false}
            title="Recursion node grew from 29% to 46% mastery (static)"
          />
        </Row>
      </Section>

      <Section title="ConceptNeighbourhood — the three presets">
        <Row label="quiz home · 320×204">
          <ConceptNeighbourhood
            centre={CENTRE}
            siblings={SIBLINGS}
            courseColor={COURSE_COLOR}
            width={320}
            height={204}
            scale={2}
            ariaLabel="Recursion and its neighbours on your knowledge tree"
          />
        </Row>
        <Row label="concept dialog · 300×200">
          <ConceptNeighbourhood
            centre={CENTRE}
            siblings={SIBLINGS}
            courseColor={COURSE_COLOR}
            width={300}
            height={200}
            scale={2}
            ariaLabel="Recursion and its neighbours on your knowledge tree"
          />
        </Row>
        <Row label="results · 640×212, growth centre">
          <ConceptNeighbourhood
            centre={CENTRE}
            siblings={SIBLINGS}
            courseColor={COURSE_COLOR}
            width={640}
            height={212}
            scale={2.5}
            centreVariant={{ kind: "growth", before: 0.29, after: 0.46 }}
            ariaLabel="Recursion node grew from 29% to 46% mastery"
          />
        </Row>
        <Row label="one sibling, and none">
          <ConceptNeighbourhood
            centre={CENTRE}
            siblings={SIBLINGS.slice(0, 1)}
            courseColor={COURSE_COLOR}
            width={320}
            height={204}
            scale={2}
            ariaLabel="Recursion and its one neighbour"
          />
          <ConceptNeighbourhood
            centre={CENTRE}
            siblings={[]}
            courseColor={COURSE_COLOR}
            width={320}
            height={204}
            scale={2}
            ariaLabel="Recursion, on its own"
          />
        </Row>
      </Section>
    </div>
  );
}

/** Four masteries, one per tier, so the opacity ramp is visible side by side. */
const marks = {
  recursion: { nodeId: "recursion", mastery: 0.29, tier: "struggling" },
  baseCases: { nodeId: "base-cases", mastery: 0.52, tier: "learning" },
  mastered: { nodeId: "determinants", mastery: 0.85, tier: "mastered" },
  unexplored: { nodeId: "tail-recursion", mastery: 0.05, tier: "unexplored" },
} as const;
