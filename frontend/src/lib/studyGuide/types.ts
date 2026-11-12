/**
 * The study-guide contract, mirrored from `backend/models/study_guide.py`.
 *
 * That file owns the shape. Change it there first, then here, then the shared
 * fixture `backend/tests/fixtures/study_guide_contract.json`, which a backend
 * test validates against the Pydantic models and the frontend tests render.
 */

export type Goal = "practice" | "review" | "exam_prep";
export type Depth = "cram" | "standard" | "deep";
export type ScopeKind = "exam" | "assignment" | "course";
export type GuideStatus = "generating" | "ready" | "failed";
export type SectionStatus = "queued" | "written" | "failed";
/** `config.get_mastery_tier`'s vocabulary. */
export type Tier = "mastered" | "learning" | "struggling" | "unexplored";
export type Feedback = "yes" | "no";

/** The source id of the student's own quiz history (never a document). */
export const QUIZ_HISTORY_SOURCE = "quiz-history";

// ── Prose ────────────────────────────────────────────────────────────────────

export interface Paragraph {
  /** `**term**` marks a key term to highlight; `$...$` is inline math. */
  text: string;
  /** Source ids this paragraph draws on. */
  citations: string[];
}

/** A passage. Skim mode shows `summary` in its place, or nothing when null. */
export interface ProseItem {
  type: "prose";
  id: string;
  paragraphs: Paragraph[];
  summary: string | null;
}

// ── Blocks ───────────────────────────────────────────────────────────────────

export interface ChartPoint {
  x: number;
  y: number;
}

export interface ChartSeries {
  label: string;
  points: ChartPoint[];
  /** `after` = drawn dashed and only in the After state. */
  state: "both" | "after";
}

export interface ChartMarker {
  x: number;
  y: number;
  x_label: string;
  y_label: string;
  state: "before" | "after";
}

export interface ChartReadout {
  label: string;
  before: string;
  after: string;
  change: string;
}

export interface ChartBlock {
  type: "chart";
  id: string;
  title: string;
  x_label: string;
  y_label: string;
  series: ChartSeries[];
  markers: ChartMarker[];
  readouts: ChartReadout[];
  after_label: string;
  alt: string;
  source_id: string | null;
  /** Decided by the server: true unless every number is in the cited source. */
  illustrative: boolean;
}

export interface Mistake {
  title: string;
  fix: string;
  evidence_id: string;
  /** Stamped by the server from the real quiz history. */
  evidence: string;
}

export interface MistakesBlock {
  type: "mistakes";
  id: string;
  title: string;
  mistakes: Mistake[];
}

export interface FormulaBlock {
  type: "formula";
  id: string;
  name: string;
  /** LaTeX, no `$` delimiters. */
  latex: string;
  spoken: string;
  source_id: string | null;
}

export interface WorkedStep {
  title: string;
  math: string;
  why: string;
}

export interface WorkedExampleBlock {
  type: "worked_example";
  id: string;
  title: string;
  problem: string;
  steps: WorkedStep[];
  source_id: string | null;
}

export interface ComparisonRow {
  label: string;
  cells: string[];
  emphasis: boolean;
}

export interface ComparisonBlock {
  type: "comparison";
  id: string;
  title: string;
  columns: string[];
  rows: ComparisonRow[];
}

export interface ConceptMapNode {
  /** A concept name; its mastery is `GuideDetail.mastery[concept]`. */
  concept: string;
  step: string;
}

export interface ConceptMapBlock {
  type: "concept_map";
  id: string;
  title: string;
  nodes: ConceptMapNode[];
}

export interface KeyTerm {
  term: string;
  definition: string;
}

export interface KeyTermsBlock {
  type: "key_terms";
  id: string;
  title: string;
  terms: KeyTerm[];
}

export type CheckOptionId = "a" | "b" | "c" | "d";

export interface CheckOption {
  id: CheckOptionId;
  text: string;
}

/**
 * `correct_id` and both explanations are null until the student has answered;
 * the answer call returns them.
 */
export interface CheckBlock {
  type: "check";
  id: string;
  question: string;
  options: CheckOption[];
  correct_id: CheckOptionId | null;
  explain_correct: string | null;
  explain_incorrect: string | null;
  concept: string | null;
}

export type Block =
  | ChartBlock
  | MistakesBlock
  | FormulaBlock
  | WorkedExampleBlock
  | ComparisonBlock
  | ConceptMapBlock
  | KeyTermsBlock
  | CheckBlock;

export type Item = ProseItem | Block;

export const BLOCK_TYPES = [
  "chart",
  "mistakes",
  "formula",
  "worked_example",
  "comparison",
  "concept_map",
  "key_terms",
  "check",
] as const satisfies readonly Block["type"][];

// ── The guide ────────────────────────────────────────────────────────────────

/** `id` is `document:<id>` for the student's own material, or quiz history. */
export interface Source {
  id: string;
  name: string;
  /** PDF, DOCX, PPTX, or Sapling. */
  kind: string;
}

export interface Section {
  id: string;
  title: string;
  /** The graph concept this section teaches (exact name), or null. */
  concept: string | null;
  /** Mastery when the guide was written. `mastered` opens collapsed. */
  tier: Tier;
  /** Share of the guide, 1-100. */
  weight: number;
  one_line: string;
  status: SectionStatus;
  items: Item[];
}

export interface GuideContent {
  title: string;
  deck: string;
  takeaways: string[];
  sections: Section[];
  sources: Source[];
  scope_label: string;
}

// ── Wire shapes ──────────────────────────────────────────────────────────────

export interface SectionBar {
  title: string;
  tier: Tier;
  weight: number;
}

export interface GuideCounts {
  sections: number;
  blocks: number;
  practice: number;
  minutes: number;
}

/** One guide on the Study Guides home (and in the Library when saved). */
export interface GuideCard {
  id: string;
  title: string;
  course_id: string;
  course_name: string;
  /** The class's short code ("CS 101"); its name when it has none. */
  course_code: string;
  semester: string | null;
  scope_kind: ScopeKind;
  scope_label: string;
  goal: Goal;
  depth: Depth;
  status: GuideStatus;
  generated_at: string | null;
  created_at: string;
  saved_at: string | null;
  /** Lectures added to the class since the guide was made. */
  new_materials: number;
  bars: SectionBar[];
  counts: GuideCounts;
}

export interface CheckAnswer {
  option_id: string;
  correct: boolean;
}

/** One guide, as the reader renders it. */
export interface GuideDetail extends GuideCard {
  content: GuideContent;
  scope_id: string | null;
  due_date: string | null;
  use_history: boolean;
  read_sections: string[];
  answers: Record<string, CheckAnswer>;
  feedback: Feedback | null;
  /** Live mastery tier per concept name the guide mentions. */
  mastery: Record<string, Tier>;
}

/** One thing a guide can be for. `id` is null for the whole course. */
export interface ScopeOption {
  kind: ScopeKind;
  id: string | null;
  title: string;
  due_date: string | null;
  suggested_material_ids: string[];
}

export interface MaterialOption {
  id: string;
  file_name: string;
  category: string;
  created_at: string;
}

export interface GuideOptions {
  scopes: ScopeOption[];
  materials: MaterialOption[];
}

/** The New study guide modal's choices. */
export interface GuideRequest {
  course_id: string;
  semester?: string | null;
  scope_kind: ScopeKind;
  scope_id: string | null;
  goal: Goal;
  depth: Depth;
  material_ids: string[];
  use_history: boolean;
}

export interface PlanSection {
  title: string;
  tier: Tier;
  weight: number;
}

/** The planned outline: decided from the choices, before any model runs. */
export interface GuidePlan {
  sections: PlanSection[];
  minutes: number;
}

/** Small state changes from the reader. Omitted fields are left alone. */
export interface GuidePatch {
  read_sections?: string[];
  saved?: boolean;
  feedback?: Feedback;
}

export interface GuideState {
  read_sections: string[];
  saved_at: string | null;
  feedback: Feedback | null;
}

/**
 * `resume` writes whatever is still queued. `update` folds in material added
 * since. `regenerate` rewrites the whole guide. The last two keep the
 * previous version.
 */
export type GenerateMode = "resume" | "update" | "regenerate";

export interface MasteryChange {
  concept: string;
  before: Tier;
  after: Tier;
}

export interface AnswerResult {
  correct: boolean;
  correct_id: CheckOptionId;
  explanation: string;
  /** False when the block had already been answered: only the first counts. */
  counted: boolean;
  mastery: MasteryChange | null;
}

/** `data` of a `status` stream event; the label is the event's `message`. */
export interface GenerationStep {
  step: number;
  total: number;
}
