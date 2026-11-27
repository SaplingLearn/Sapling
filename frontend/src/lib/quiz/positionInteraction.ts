/**
 * W7.2 Position (design kit 7.12) — marker→stop ↔ `answerText` for a
 * short_answer wire.
 *
 * DISPLAY + SESSION STATE ONLY. Generation does not emit `interaction` yet.
 * Encode matches Build: `markerId=stopId;…`.
 */

import type {
  PositionInteraction,
  PositionInteractionMarker,
  PositionInteractionStop,
  WireQuestion,
} from "./types";

export type PositionAssignment = Record<string, string | null>;

const SEP_SLOT = ";";
const SEP_NAME = "=";

function safeId(raw: unknown): string {
  if (typeof raw !== "string") return "";
  const id = raw.trim();
  if (!id || id.includes(SEP_SLOT) || id.includes(SEP_NAME)) return "";
  return id;
}

function cleanMarkers(raw: PositionInteractionMarker[] | undefined): PositionInteractionMarker[] {
  const seen = new Set<string>();
  const markers: PositionInteractionMarker[] = [];
  for (const it of raw ?? []) {
    const id = safeId(it?.id);
    const label = typeof it?.label === "string" ? it.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    markers.push({ id, label });
  }
  return markers;
}

function cleanStops(raw: PositionInteractionStop[] | undefined): PositionInteractionStop[] {
  const seen = new Set<string>();
  const stops: PositionInteractionStop[] = [];
  for (const it of raw ?? []) {
    const id = safeId(it?.id);
    const label = typeof it?.label === "string" ? it.label.trim() : "";
    if (!id || !label || seen.has(id)) continue;
    seen.add(id);
    stops.push({ id, label });
  }
  return stops;
}

/** ≥2 markers, ≥2 stops, no id collisions across markers/stops. */
export function asPositionInteraction(
  raw: WireQuestion["interaction"] | null | undefined,
): PositionInteraction | null {
  if (!raw || raw.kind !== "position") return null;
  const markers = cleanMarkers(raw.markers);
  const stops = cleanStops(raw.stops);
  if (markers.length < 2 || stops.length < 2) return null;
  const stopIds = new Set(stops.map(s => s.id));
  if (markers.some(m => stopIds.has(m.id))) return null;
  const axisLabel =
    typeof raw.axisLabel === "string" && raw.axisLabel.trim()
      ? raw.axisLabel.trim()
      : undefined;
  return {
    kind: "position",
    markers,
    stops,
    ...(axisLabel ? { axisLabel } : {}),
  };
}

export function emptyPositionAssignment(markers: PositionInteractionMarker[]): PositionAssignment {
  return Object.fromEntries(markers.map(m => [m.id, null]));
}

export function isPositionComplete(
  interaction: PositionInteraction,
  assign: PositionAssignment,
): boolean {
  const stopIds = new Set(interaction.stops.map(s => s.id));
  return interaction.markers.every(m => {
    const stop = assign[m.id];
    return typeof stop === "string" && stopIds.has(stop);
  });
}

export function encodePositionAnswer(
  interaction: PositionInteraction,
  assign: PositionAssignment,
): string {
  return interaction.markers
    .map(m => `${m.id}${SEP_NAME}${assign[m.id] ?? ""}`)
    .join(SEP_SLOT);
}

export function decodePositionAnswer(
  interaction: PositionInteraction,
  raw: string | null | undefined,
): PositionAssignment {
  const assign = emptyPositionAssignment(interaction.markers);
  const text = (raw ?? "").trim();
  if (!text) return assign;
  const byMarker = new Set(interaction.markers.map(m => m.id));
  const byStop = new Set(interaction.stops.map(s => s.id));
  const taken = new Set<string>();
  for (const part of text.split(SEP_SLOT)) {
    const eq = part.indexOf(SEP_NAME);
    if (eq <= 0) continue;
    const markerId = part.slice(0, eq).trim();
    const stopId = part.slice(eq + 1).trim();
    if (!byMarker.has(markerId) || !byStop.has(stopId) || taken.has(stopId)) continue;
    if (assign[markerId] != null) continue;
    assign[markerId] = stopId;
    taken.add(stopId);
  }
  return assign;
}

/** Place marker on stop (or tray when stop is null). Occupied stop frees prior marker. */
export function placePositionMarker(
  assign: PositionAssignment,
  markerId: string,
  stopId: string | null,
): PositionAssignment {
  if (!(markerId in assign)) return assign;
  const next: PositionAssignment = { ...assign, [markerId]: stopId };
  if (stopId) {
    for (const [id, at] of Object.entries(assign)) {
      if (id !== markerId && at === stopId) next[id] = null;
    }
  }
  return next;
}
