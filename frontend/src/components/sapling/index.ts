/* Sapling redesign foundation (prompt 01) — import from "@/components/sapling".
 * Styles: components/sapling/sapling.css, loaded once by ShellFrame. */
export {
  BotanicalIcon,
  SaplingWordmark,
  BOTANICAL_ASSETS,
  SAPLING_ASSET_BASE,
  botanicalIconSrc,
  type BotanicalIconName,
  type BotanicalIconProps,
} from "./BotanicalIcon";
export {
  SaplingSurface,
  PageHeading,
  SectionHeading,
  SaplingAction,
  SelectableRow,
  ChoiceGroup,
  GoalSummary,
  PhaseStrip,
  StatusMessage,
  LOOP_STAGES,
  stageIndexForPhase,
  type PageHeadingProps,
  type SaplingActionProps,
  type SelectableRowProps,
  type ChoiceOption,
  type ChoiceGroupProps,
  type GoalSummaryProps,
  type StatusMessageProps,
} from "./primitives";
export { ContextPanel, ContextSheet, type ContextPanelProps, type ContextSheetProps } from "./ContextPanel";
export { SaplingComposer, isSendKey, type ComposerState, type SaplingComposerProps } from "./Composer";
