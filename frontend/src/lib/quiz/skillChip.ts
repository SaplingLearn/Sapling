/**
 * W7 Bloom-ish skill chip — display only.
 * Formula: docs/learning-loop/w7-skill-chip.md.
 */

export type SkillChipLabel =
  | "Remember"
  | "Understand"
  | "Apply"
  | "Analyze"
  | "Evaluate"
  | "Create";

const KIT_SKILL: Record<string, SkillChipLabel> = {
  calculate: "Apply",
  position: "Apply",
  compare: "Analyze",
  highlight: "Analyze",
  connect: "Analyze",
  rank: "Evaluate",
  explain: "Evaluate",
  build: "Create",
  sequence: "Create",
  dialogue: "Create",
  sort: "Create",
  label: "Create",
};

/** Derive a Bloom-ish skill label from wire type / kit / difficulty. */
export function skillChipLabel({
  type,
  difficulty,
  interactionKind,
}: {
  type?: string | null;
  difficulty?: string | null;
  interactionKind?: string | null;
}): SkillChipLabel | null {
  const kind = (interactionKind ?? "").trim().toLowerCase();
  if (kind && KIT_SKILL[kind]) return KIT_SKILL[kind];

  const t = (type ?? "").trim().toLowerCase();
  const d = (difficulty ?? "").trim().toLowerCase();

  if (t === "numeric" || t === "symbolic") return "Apply";
  if (t === "multiple_choice") {
    return d === "easy" ? "Remember" : "Understand";
  }
  if (t === "short_answer") {
    return d === "easy" ? "Remember" : "Understand";
  }
  return null;
}
