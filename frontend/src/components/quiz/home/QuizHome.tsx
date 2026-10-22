"use client";

/**
 * Quiz home (§5 B1) — `phase: home | configuring`.
 *
 * Two columns. On the left, one proposal you can start in a single click,
 * with its neighbourhood on the tree drawn underneath. On the right, "Choose a
 * topic": the whole due set as one row, then every concept on the tree. The
 * old screen opened on an empty course/concept dropdown and asked the student
 * to know what they wanted; this one arrives with an answer and keeps every
 * alternative in view.
 *
 * Everything on it is derived, never invented: the ranking is
 * `lib/quiz/proposals` (a cited mirror of `graph_service.get_recommendations`,
 * R-7), the meta and rationale lines are its formatters, the option lists come
 * off `GET /api/quiz/config`, and the marks are the tree's own arithmetic
 * through `ConceptNode`, and the neighbourhood window is the tree's own 2D
 * renderer (`LiveNeighbourhood`).
 *
 * The card has three shapes, chosen by how you arrived (§6): a concept (the
 * default, and every `?concept=` / `?topic=` deep link), a course (`?course=`)
 * and the due set (`?scope=due`). The last two run as a queue of single-concept
 * attempts, because `/generate` is per concept (R-4).
 */

import React from "react";
import { Button, EmptyState, InlineBanner } from "@/components/ui";
import { Skeleton } from "@/components/Skeleton";
import { useToast } from "@/components/ToastProvider";
import { apiToGraphNode } from "@/lib/data";
import { siblingsFor } from "@/lib/graph/neighbourhood";
import { cancelTarget } from "@/lib/quiz/exits";
import type { SessionConfig } from "@/lib/quiz/machine";
import { savePrefs } from "@/lib/quiz/prefs";
import {
  colorFor,
  entrySelection,
  latestCompletedAttempt,
  metaLine,
  queueFor,
  rationaleFor,
  type Candidate,
} from "@/lib/quiz/proposals";
import { QUEUE_COUNT, QUEUE_MAX } from "@/lib/quiz/session";
import type { EntryRequest } from "@/lib/quiz/source";
import type { QuizConfig, QuizSession, SourceKind } from "@/lib/quiz/types";
import { fallbackDefinition, type QuizHome as QuizHomeData } from "@/lib/quiz/useQuizHome";
import type { QuizActions } from "@/lib/quiz/useQuizSession";
import { AdjustDialog } from "./AdjustDialog";
import { ConceptDialog } from "./ConceptDialog";
import { LiveNeighbourhood } from "./LiveNeighbourhood";
import { TopicList } from "./TopicList";
import { accentStyle } from "./accent";
import "./home.css";

export interface QuizHomeProps {
  userId: string;
  home: QuizHomeData;
  config: QuizConfig | null;
  entry: EntryRequest;
  session: QuizSession;
  actions: QuizActions;
}

/** The card's three shapes (§5 B1.2). `course` and `due` run as queues. */
type CardMode = "concept" | "course" | "due";

/** The neighbourhood window's height while the tree loads (`home.css`). */
const GRAPH_SKELETON_HEIGHT = 220;

/** Why a deep-linked concept is the one on offer (§5 B1.2). */
const DEEP_LINK_RATIONALE: Partial<Record<SourceKind, string>> = {
  tree: "From your tree",
  notes: "From your note",
};
const DEFAULT_DEEP_LINK_RATIONALE = "Suggested for you";

/** §6: a link into a term the student isn't looking at. */
const UNRESOLVED_COPY = "That concept isn't in your current semester";

export function QuizHome({ userId, home, config, entry, session, actions }: QuizHomeProps) {
  const toast = useToast();
  const [adjustOpen, setAdjustOpen] = React.useState(false);
  const [dialogNodeId, setDialogNodeId] = React.useState<string | null>(null);
  const [topicQuery, setTopicQuery] = React.useState("");

  // ── What the card is about ────────────────────────────────────────────

  const selection = React.useMemo(
    () => entrySelection(entry, home.nodes, home.courses),
    [entry, home.nodes, home.courses],
  );

  // A deep link naming something outside the active semester says so once and
  // then gets out of the way — the ordinary home renders underneath (§6).
  const toasted = React.useRef(false);
  React.useEffect(() => {
    if (toasted.current || home.status !== "ready" || !selection.unresolved) return;
    toasted.current = true;
    toast.info(UNRESOLVED_COPY);
  }, [home.status, selection.unresolved, toast]);

  const courseQueue = React.useMemo(
    () => (entry.course ? queueFor("course", home.nodes, entry.course) : []),
    [entry.course, home.nodes],
  );
  const dueQueue = React.useMemo(() => queueFor("due", home.nodes), [home.nodes]);

  const mode: CardMode = selection.conceptId
    ? "concept"
    : entry.course && courseQueue.length > 0
      ? "course"
      : entry.scope === "due" && dueQueue.length > 0
        ? "due"
        : "concept";

  /**
   * A concept as the card and the dialogs want it. Ranked candidates come with
   * their rationale already resolved; anything else (a mastered concept picked
   * out of the list, say) is built the same way `rankCandidates` would.
   */
  const candidateFor = React.useCallback(
    (nodeId: string | null | undefined): Candidate | null => {
      if (!nodeId) return null;
      const ranked = home.candidates.find(c => c.node.id === nodeId);
      if (ranked) return ranked;
      const node = home.nodes.find(n => n.id === nodeId);
      if (!node) return null;
      const course = home.courses.find(c => c.course_id === node.course_id) ?? null;
      const lastAttempt = latestCompletedAttempt(node.id, home.attempts);
      return {
        node,
        course,
        color: colorFor(node, course),
        rationale: rationaleFor(node, lastAttempt),
        ...(lastAttempt ? { lastAttempt } : {}),
      };
    },
    [home.candidates, home.nodes, home.courses, home.attempts],
  );

  const card = React.useMemo(() => {
    if (mode === "course") return candidateFor(courseQueue[0]);
    if (mode === "due") return candidateFor(dueQueue[0]);
    return candidateFor(selection.conceptId) ?? home.primary;
  }, [mode, candidateFor, courseQueue, dueQueue, selection.conceptId, home.primary]);

  const entryCourse = React.useMemo(
    () => home.courses.find(c => c.course_id === entry.course) ?? null,
    [home.courses, entry.course],
  );

  // ── The little constellation ──────────────────────────────────────────
  //
  // `siblingsFor` works on the adapted `lib/data` node shape (colour resolved,
  // `name` rather than `concept_name`) — the same one the tree feeds its graph,
  // and the one `QuizScreen` already adapts for the results screen.
  const viewNodes = React.useMemo(
    () => home.nodes.map(n => apiToGraphNode(n, home.courses)),
    [home.nodes, home.courses],
  );

  const siblingsOf = React.useCallback(
    (nodeId: string | undefined) => (nodeId ? siblingsFor(nodeId, viewNodes, home.edges) : []),
    [viewNodes, home.edges],
  );

  /** The `n` in "{Course} · {tier} · {n} connected concepts" (R-8's fallback). */
  const connectedTo = React.useCallback(
    (nodeId: string | undefined) =>
      nodeId ? home.edges.filter(e => e.source === nodeId || e.target === nodeId).length : 0,
    [home.edges],
  );


  // ── Copy ──────────────────────────────────────────────────────────────

  const accent = card?.color ?? null;
  const queued = mode !== "concept";
  const conceptName = card?.node.concept_name ?? "";
  const courseCode = (mode === "course" ? entryCourse : card?.course)?.course_code ?? "";

  const title =
    mode === "course"
      ? `Practice ${courseCode}`
      : mode === "due"
        ? "Review everything due"
        : conceptName;

  const meta =
    mode === "course"
      ? `${courseQueue.length} concepts due`
      : mode === "due"
        ? `${home.due.count} concepts across ${home.due.courseCount} courses · starting with the ${Math.min(home.due.count, QUEUE_MAX)} weakest`
        : card
          ? metaLine(card.node)
          : "";

  // Only a deep link explains itself on the card: it is the one arrival whose
  // proposal the student did not just get from the ranking.
  const rationale =
    mode === "concept" && selection.conceptId && card
      ? DEEP_LINK_RATIONALE[entry.source.kind] ?? DEFAULT_DEEP_LINK_RATIONALE
      : null;

  // R-8's sentence, fetched by the hook for the concept the CARD shows — a deep
  // link included (A2 fix round 5). The built sentence stands in while the call
  // is in flight or after it fails. The two queued shapes show no definition at
  // all: it describes one concept and would read as a caption for the wrong
  // thing under "Practice CS101".
  const definition = queued
    ? null
    : home.cardDescription ?? (card ? fallbackDefinition(card, connectedTo(card.node.id)) : "");

  const feedbackSuffix = session.config.feedback === "as-you-go" ? " · answers as you go" : "";
  const configLine = queued
    ? `${QUEUE_COUNT} questions each, ${session.config.difficulty}${feedbackSuffix}`
    : `${session.config.count} questions, ${session.config.difficulty}${feedbackSuffix}`;

  // ── Starting ──────────────────────────────────────────────────────────

  const startConcept = React.useCallback(
    (candidate: Candidate, cfg: SessionConfig) => {
      actions.start(
        {
          intent: "practice",
          scope: { kind: "concept", conceptId: candidate.node.id },
          conceptId: candidate.node.id,
          courseId: candidate.node.course_id ?? null,
        },
        cfg,
      );
    },
    [actions],
  );

  const startQueue = React.useCallback(
    (kind: "course" | "due", queue: string[], cfg: SessionConfig, courseId?: string) => {
      if (queue.length === 0) return;
      const first = queue[0];
      actions.start(
        {
          intent: kind === "due" ? "review" : "practice",
          scope:
            kind === "due"
              ? { kind: "due", queue }
              : { kind: "course", courseId: courseId ?? "", queue },
          conceptId: first,
          courseId: home.nodes.find(n => n.id === first)?.course_id ?? null,
        },
        cfg,
      );
    },
    [actions, home.nodes],
  );

  /** The card's own Start, in whichever shape it currently has. */
  const startCard = React.useCallback(
    (cfg: SessionConfig) => {
      if (mode === "course") return startQueue("course", courseQueue, cfg, entry.course);
      if (mode === "due") return startQueue("due", dueQueue, cfg);
      if (card) startConcept(card, cfg);
    },
    [mode, startQueue, courseQueue, dueQueue, entry.course, card, startConcept],
  );

  /** Remember the choices a dialog was started with (§5 B1.6). `setConfig`
   *  persists on its own; `start` does not. */
  const remember = (cfg: SessionConfig) =>
    savePrefs({ count: cfg.count, difficulty: cfg.difficulty, feedback: cfg.feedback,
      ...(cfg.questionFormat ? { questionFormat: cfg.questionFormat } : {}) });

  // A queued session is QUEUE_COUNT questions per concept by default (R-4).
  // That is what the card starts with AND what its Adjust dialog opens on —
  // otherwise "Start · 5 medium" would quietly run three-question attempts.
  const effectiveConfig: SessionConfig = queued
    ? { ...session.config, count: QUEUE_COUNT }
    : session.config;

  // ── Dialogs ───────────────────────────────────────────────────────────

  const dialogCandidate = React.useMemo(
    () => candidateFor(dialogNodeId),
    [candidateFor, dialogNodeId],
  );

  const openAdjust = (open: boolean) => {
    setAdjustOpen(open);
    // `configuring` is the machine's own name for "the adjust dialog is open".
    actions.configure(open);
  };

  const openConcept = (nodeId: string) => {
    if (adjustOpen) openAdjust(false);
    setDialogNodeId(nodeId);
  };

  // ── Regions ───────────────────────────────────────────────────────────

  const resumable = home.resumable;
  const resumeName = resumable
    ? home.nodes.find(n => n.id === resumable.attempt.concept_node_id)?.concept_name
      ?? home.attempts.find(a => a.quiz_id === resumable.attempt.quiz_id)?.concept_name
      ?? "a concept"
    : "";
  const resumeTotal = resumable
    ? resumable.attempt.questions.length || resumable.attempt.total || 0
    : 0;

  // A true full-bleed band: it renders OUTSIDE the content column (A2's
  // `.quiz-body--home` is padding-free for exactly this), so `InlineBanner`'s
  // own page padding and bottom rule reach both edges under the TopBar with
  // nothing here overriding them.
  const resumeStrip = resumable ? (
    <InlineBanner
      testid="quiz-resume-strip"
      actions={
        <>
          <Button data-testid="quiz-resume" onClick={() => actions.resume(resumable.attempt.quiz_id)}>
            Resume
          </Button>
          <Button
            variant="link"
            data-testid="quiz-resume-discard"
            onClick={() => home.discard(resumable.attempt.quiz_id)}
          >
            Discard
          </Button>
        </>
      }
    >
      {`You left a quiz on ${resumeName} — ${resumable.answered} of ${resumeTotal} answered`}
    </InlineBanner>
  ) : null;

  const conceptCount = React.useMemo(
    () => home.nodes.filter(n => !n.is_subject_root).length,
    [home.nodes],
  );

  const cancel = (
    <Button
      variant="link"
      data-testid="quiz-cancel"
      onClick={() => actions.exit(cancelTarget(session))}
    >
      Cancel
    </Button>
  );

  /**
   * The Cancel row for the screens that are not the two columns (§5 B1.8): an
   * empty tree, no courses, a failed load. They still need a way back to
   * wherever the student came from. The two columns (and their skeleton) pin
   * Cancel to their own top-right corner instead, so it stays at the top of
   * the screen when the columns stack and does not move as the load resolves.
   */
  const cardHead = <div className="quiz-home__card-head">{cancel}</div>;

  const topicsHead = <div className="label-micro quiz-eyebrow">Choose a topic</div>;

  const proposal = card ? (
    <section className="quiz-home__proposal" data-testid="quiz-proposal">
      <div className="label-micro quiz-eyebrow">Ready for you</div>
      <div className="h-serif quiz-home__name" data-testid="quiz-proposal-name">
        {title}
      </div>

      {meta && <p className="quiz-home__meta">{meta}</p>}
      {rationale && <p className="quiz-home__rationale">{rationale}</p>}
      {definition && <p className="quiz-home__definition">{definition}</p>}
      <p className="quiz-home__config">{configLine}</p>

      <LiveNeighbourhood
        centreId={card.node.id}
        nodes={viewNodes}
        edges={home.edges}
        onPick={openConcept}
        ariaLabel={`${card.node.concept_name} and its neighbours on your knowledge tree`}
      />

      <div className="quiz-home__actions">
        <Button
          variant="primary"
          data-testid="quiz-start"
          onClick={() => startCard(effectiveConfig)}
        >
          Start
        </Button>
        <Button
          variant="link"
          data-testid="quiz-adjust"
          aria-pressed={adjustOpen}
          data-active={adjustOpen ? "true" : undefined}
          onClick={() => openAdjust(!adjustOpen)}
        >
          Adjust
        </Button>
      </div>
    </section>
  ) : (
    // Every concept is mastered: there is nothing to propose, but every
    // concept is still in the list beside this, so it is a signpost rather
    // than a dead end.
    <EmptyState
      testid="quiz-empty-state"
      title="Nothing needs review right now"
      body="Every concept on your tree is in good shape. Pick one from the list to quiz it anyway."
    />
  );

  // The card's own concept is not offered again beside it. A queued card is
  // titled for the course or the due set, not its first concept, so there the
  // first concept stays in the list. A search finds everything, the card's
  // concept included: hiding a match the student typed would read as missing.
  const query = topicQuery.trim().toLowerCase();
  const hiddenTopic = mode === "concept" && !query ? card?.node.id : undefined;
  const topicGroups = React.useMemo(
    () =>
      home.byCourse
        .map(g => ({
          ...g,
          nodes: g.nodes.filter(
            n =>
              n.id !== hiddenTopic &&
              (!query ||
                n.concept_name.toLowerCase().includes(query) ||
                g.course.course_code.toLowerCase().includes(query)),
          ),
        }))
        .filter(g => g.nodes.length > 0),
    [home.byCourse, hiddenTopic, query],
  );

  // On a due card the card already IS "Review everything due"; while
  // searching, the list is answering the search.
  const dueRow =
    home.due.count > 0 && mode !== "due" && !query ? (
      <button
        type="button"
        className="quiz-home__row"
        data-testid="quiz-review-due"
        onClick={() => startQueue("due", dueQueue, { ...session.config, count: QUEUE_COUNT })}
      >
        <span className="quiz-home__row-mark quiz-home__row-mark--hollow" />
        <span className="h-serif quiz-home__row-name">Review everything due</span>
        <span className="quiz-home__row-spacer" />
        <span className="quiz-home__row-meta">
          {`${home.due.count} concepts across ${home.due.courseCount} courses`}
        </span>
      </button>
    ) : null;

  const search = (
    <input
      type="search"
      className="field quiz-home__search"
      data-testid="quiz-topic-search"
      placeholder="Search your concepts"
      aria-label="Search your concepts"
      value={topicQuery}
      onChange={e => setTopicQuery(e.target.value)}
    />
  );

  const topics = (
    <section className="quiz-home__topics-col" aria-label="Choose a topic">
      {topicsHead}
      {search}
      {/* Capped to the proposal's height and scrolled inside (`home.css`). */}
      <div className="quiz-home__topics-scroll">
        {topicGroups.length > 0 || dueRow ? (
          <TopicList groups={topicGroups} onPick={openConcept} lead={dueRow} />
        ) : (
          <p className="quiz-home__topics-empty" data-testid="quiz-topic-search-empty">
            {query ? `No concepts match “${topicQuery.trim()}”` : "Nothing else on your tree yet"}
          </p>
        )}
      </div>
    </section>
  );

  /** The two columns, with whatever each one holds. */
  const columns = (lead: React.ReactNode, side: React.ReactNode) => (
    <div className="quiz-home__grid">
      <div className="quiz-home__grid-cancel">{cancel}</div>
      <div className="quiz-home__lead">{lead}</div>
      <div className="quiz-home__grid-divider" />
      {side}
    </div>
  );

  const skeleton = columns(
    <div className="quiz-home__skeleton-main">
      <Skeleton width={90} height={10} />
      <Skeleton width={240} height={32} />
      <Skeleton width={220} height={12} />
      <Skeleton width={380} height={13} />
      <Skeleton width={340} height={13} />
      <Skeleton width={160} height={16} />
      <Skeleton width="100%" height={GRAPH_SKELETON_HEIGHT} />
      <Skeleton width={120} height={34} />
    </div>,
    <div className="quiz-home__topics-col">
      {topicsHead}
      <Skeleton width="100%" height={36} />
      <div className="quiz-home__skeleton-rows">
        {[0, 1, 2, 3, 4, 5].map(i => (
          <Skeleton key={i} width="100%" height={18} />
        ))}
      </div>
    </div>,
  );

  const errorCard = (
    <div className="quiz-error" role="alert" data-testid="quiz-home-error">
      <h2 className="h-serif quiz-error__title">We couldn&apos;t load your tree</h2>
      <p className="quiz-error__body">{home.error?.message}</p>
      <div className="quiz-error__actions">
        <Button variant="primary" data-testid="quiz-home-retry" onClick={() => home.refresh()}>
          Retry
        </Button>
      </div>
    </div>
  );

  /** Which arrival the screen is rendering. Named once so the Cancel row
   *  above the body knows whether the two columns already carry Cancel. */
  const view =
    home.status === "error"
      ? "error"
      : home.status === "loading"
        ? "loading"
        : home.courses.length === 0
          ? "no-courses"
          : conceptCount === 0
            ? "empty-tree"
            : "home";

  const body = () => {
    if (view === "error") return errorCard;
    if (view === "loading") return skeleton;

    if (view === "no-courses") {
      return (
        <EmptyState
          testid="quiz-empty-state"
          title="Add a course to start quizzing"
          body="Quizzes come from the concepts on your tree, and your tree grows out of your courses."
          action={{ label: "Go to your dashboard", href: "/dashboard" }}
        />
      );
    }

    if (view === "empty-tree") {
      return (
        <EmptyState
          testid="quiz-empty-state"
          title="Your tree is empty"
          body="Upload notes or talk to the tutor and concepts will appear here."
          action={
            <>
              <a className="btn btn--primary" href="/library">
                Go to your library
              </a>
              <a className="btn" href="/learn">
                Talk to the tutor
              </a>
            </>
          }
        />
      );
    }

    return columns(proposal, topics);
  };

  return (
    <div className="quiz-home" data-testid="quiz-home" style={accentStyle(accent)}>
      {resumeStrip}

      {/* A2's `.quiz-body--home` is padding-free so the strip above can bleed;
          everything else gets the column and the page padding back here. The
          two are NESTED rather than stacked on one element: `box-sizing:
          border-box` is global, so a single div carrying both would eat the
          64px of page padding out of the column's measure. The design puts the
          padding outside the column. */}
      <div className="quiz-inset--home">
        <div className="quiz-col quiz-col--home">
          {/* The two columns (and their skeleton) carry Cancel in their own head. */}
          {view !== "home" && view !== "loading" && cardHead}
          {body()}
        </div>
      </div>

      {dialogCandidate && (
        <ConceptDialog
          key={dialogCandidate.node.id}
          open
          userId={userId}
          candidate={dialogCandidate}
          siblings={siblingsOf(dialogCandidate.node.id)}
          connected={connectedTo(dialogCandidate.node.id)}
          config={config}
          initialConfig={session.config}
          onCancel={() => setDialogNodeId(null)}
          onStart={cfg => {
            setDialogNodeId(null);
            remember(cfg);
            startConcept(dialogCandidate, cfg);
          }}
        />
      )}

      {adjustOpen && card && (
        <AdjustDialog
          open
          subtitle={courseCode ? `${conceptName} · ${courseCode}` : conceptName}
          accent={accent}
          config={config}
          initialConfig={effectiveConfig}
          onDone={cfg => {
            openAdjust(false);
            actions.setConfig(cfg);
          }}
          onClose={() => openAdjust(false)}
          onStart={cfg => {
            openAdjust(false);
            remember(cfg);
            startCard(cfg);
          }}
        />
      )}
    </div>
  );
}
