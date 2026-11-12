"use client";
import { Skeleton, SkeletonText } from "@/components/Skeleton";
import type { Feedback, GuideDetail } from "@/lib/studyGuide/types";

import { FeedbackRow } from "./FeedbackRow";
import { GenerationBanner, GenerationError } from "./GenerationBanner";
import { GuideHeader } from "./GuideHeader";
import { Rail } from "./rail/Rail";
import s from "./reader.module.css";
import { useBlockRegenerate } from "./blocks/useBlockRegenerate";
import { ReaderProvider, type Reader } from "./ReaderContext";
import { daysUntil, sectionPhases, type SectionPhase, type ViewMode } from "./readerModel";
import { SectionView } from "./SectionView";
import { Sources } from "./Sources";
import { Takeaways } from "./Takeaways";
import { useGeneration } from "./useGeneration";
import type { GuideUpdate } from "./useGuide";
import { useTutorHandoff } from "./useTutorHandoff";

/** The page before a guide (or its outline) is there to show. */
export function ArticleSkeleton() {
  return (
    <div className={s.article} aria-hidden="true">
      <Skeleton width={220} height={12} />
      <Skeleton width="78%" height={44} radius="var(--r-md)" />
      <Skeleton width="60%" height={18} />
      <SkeletonText lines={3} lineHeight={14} gap={12} lastWidth="88%" />
      <Skeleton height={220} radius="var(--r-lg)" />
    </div>
  );
}

export interface GuideViewProps {
  userId: string;
  guide: GuideDetail;
  mode: ViewMode;
  today: Date;
  update: GuideUpdate;
  onToggleRead: (sectionId: string) => void;
  onSave: () => void;
  onFeedback: (feedback: Feedback) => void;
}

interface ArticleProps extends Pick<GuideViewProps, "guide" | "onToggleRead" | "onSave" | "onFeedback"> {
  phases: Record<string, SectionPhase>;
  days: number | null;
  generating: boolean;
  onRegenerate: () => void;
  /** Writes what is still missing (a section that failed). */
  onResume: () => void;
}

function Article({ guide, phases, days, generating, onToggleRead, onSave, onFeedback, onRegenerate, onResume }: ArticleProps) {
  const { content } = guide;
  // A new guide has nothing to show until its outline arrives.
  if (generating && content.sections.length === 0) return <ArticleSkeleton />;
  return (
    <article className={s.article}>
      <GuideHeader guide={guide} days={days} onSave={onSave} onRegenerate={onRegenerate} />
      <Takeaways takeaways={content.takeaways} generating={generating} />
      {content.sections.map((section, i) => (
        <SectionView
          key={section.id}
          section={section}
          index={i}
          phase={phases[section.id]}
          read={guide.read_sections.includes(section.id)}
          onToggleRead={() => onToggleRead(section.id)}
          onRetry={onResume}
        />
      ))}
      <Sources sources={content.sources} />
      {!generating && <FeedbackRow feedback={guide.feedback} onFeedback={onFeedback} />}
    </article>
  );
}

/** A loaded guide: the article, the rail, and the generation that fills them. */
export function GuideView({ userId, guide, mode, today, update, onToggleRead, onSave, onFeedback }: GuideViewProps) {
  const generation = useGeneration(userId, guide.id, guide.status, update);
  const block = useBlockRegenerate(userId, guide.id, update);
  const tutor = useTutorHandoff(userId, guide.course_id);
  const generating = generation.active;
  const { failure } = generation;
  const retry = failure?.retry ?? null;
  const phases = sectionPhases(guide.content.sections, generating, generation.tried);
  const days = daysUntil(guide.due_date, today);
  const reader: Reader = {
    userId, guide, mode, generating, update,
    rewriting: block.rewriting,
    regenerateBlock: block.regenerate,
    askTutor: tutor.ask,
    tutorBusy: tutor.busy,
  };
  // A generation that ended with nothing written leaves no guide to draw:
  // the error and its Retry are the page.
  const nothingWritten = failure !== null && guide.content.sections.length === 0;
  // A request that was turned away left a ready guide as it was: the banner
  // can go. Once a run has replaced the outline, only a resume finishes it.
  const untouched = guide.status === "ready" && failure !== null && !failure.replanned;

  return (
    <ReaderProvider value={reader}>
      {failure && (
        <GenerationError
          message={failure.message}
          onRetry={retry ? () => generation.start(retry) : undefined}
          onDismiss={untouched ? generation.dismiss : undefined}
          busy={block.rewriting !== null}
        />
      )}
      {!nothingWritten && (
        <div className={`${s.shell} tool-enter`}>
          {generating && <GenerationBanner label={generation.label} step={generation.step} />}
          <div className={s.layout}>
            <Article
              guide={guide}
              phases={phases}
              days={days}
              generating={generating}
              onToggleRead={onToggleRead}
              onSave={onSave}
              onFeedback={onFeedback}
              onRegenerate={() => generation.start("regenerate")}
              onResume={() => generation.start("resume")}
            />
            <Rail
              phases={phases}
              days={days}
              updated={generation.updated}
              onToggleRead={onToggleRead}
              onUpdate={() => generation.start("update")}
            />
          </div>
        </div>
      )}
    </ReaderProvider>
  );
}
