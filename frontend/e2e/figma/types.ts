/**
 * Figma capture recipes (docs/figma/inventory/). A recipe drives the app to
 * ONE inventory state on the showcase stack; its last act asserts the state is
 * on screen. The harness (../figma-capture.spec.ts) then hands the DOM to
 * Figma's capture.js.
 *
 * Rules for recipe authors:
 * - Key = the inventory state id, verbatim (e.g. "quiz/home-ready").
 * - Desktop only (1440×900). No mobile/phone/tablet states.
 * - Prefer NON-destructive paths: the showcase DB is shared by every recipe in
 *   a run (no per-test reset). For empty/error/loading states mock the API
 *   with helpers.ts instead of mutating data.
 * - Never click anything that opens a native window.prompt/confirm/alert.
 * - End with an expect(...) that proves the state, not just the route.
 */
import type { Page } from "@playwright/test";

export type Persona = "active" | "second" | "admin" | "new" | "public";

export interface Recipe {
  /** Who is signed in. Default "active" (rich-user-active, "Maya Ellis"). */
  persona?: Persona;
  run: (page: Page) => Promise<void>;
}

export type RecipeBook = Record<string, Recipe>;
