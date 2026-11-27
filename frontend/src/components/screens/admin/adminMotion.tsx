"use client";
/**
 * Motion for the admin tables (#866): rows arrive with the app's list stagger
 * (lib/motion `list`). A row mounted later (a new range, a sort, "Show all")
 * enters the same way; at rest every row is exactly the plain <tr>. Reduced
 * motion is an opacity-only arrival, handled by the presets.
 */
import React from "react";
import { motion, type MotionProps } from "framer-motion";
import { useMotionPresets, type MotionPreset } from "@/lib/motion";

/**
 * A lib/motion preset as props for a `motion.*` element. framer-motion 11's
 * prop types reject a spread `TargetAndTransition` for `initial` (TS2322, and
 * TS2590 on the union), so the preset is typed as the props it is.
 */
export function presetProps(preset: MotionPreset): MotionProps {
  return preset as MotionProps;
}

type TbodyProps = React.ComponentProps<typeof motion.tbody>;
type TrProps = React.ComponentProps<typeof motion.tr>;
type DivProps = React.ComponentProps<typeof motion.div>;

/** A <tbody> whose StaggerRow children arrive one after another. */
export function StaggerBody(props: TbodyProps) {
  const m = useMotionPresets();
  return <motion.tbody variants={m.list.container} initial="hidden" animate="shown" {...props} />;
}

/** A <tr> inside StaggerBody. */
export function StaggerRow(props: TrProps) {
  const m = useMotionPresets();
  return <motion.tr variants={m.list.item} {...props} />;
}

/** A block whose StaggerItem children (cards, figures) arrive one after another. */
export function StaggerList(props: DivProps) {
  const m = useMotionPresets();
  return <motion.div variants={m.list.container} initial="hidden" animate="shown" {...props} />;
}

/** A child of StaggerList. */
export function StaggerItem(props: DivProps) {
  const m = useMotionPresets();
  return <motion.div variants={m.list.item} {...props} />;
}

/** Content that fades in when it replaces a loading or error state. */
export function FadeIn(props: DivProps) {
  const m = useMotionPresets();
  return <motion.div {...presetProps(m.fade)} {...props} />;
}
