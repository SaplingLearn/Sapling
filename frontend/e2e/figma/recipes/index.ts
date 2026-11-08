/** All capture recipes, keyed by inventory state id (docs/figma/inventory/). */
import type { RecipeBook } from "../types";
import { RECIPES_CORE } from "./core"; // 01 dashboard / learn / tree / graph
import { RECIPES_STUDY } from "./study"; // 02 quiz / study / flashcards / notetaker / library
import { RECIPES_GRADES } from "./grades"; // 03 gradebook / calendar / planner / achievements / social / profile
import { RECIPES_SETTINGS } from "./settings"; // 04 settings / admin / pre-shell / chrome
import { RECIPES_PUBLIC } from "./public"; // 05 landing + public pages

const books = { RECIPES_CORE, RECIPES_STUDY, RECIPES_GRADES, RECIPES_SETTINGS, RECIPES_PUBLIC };

export const RECIPES: RecipeBook = {};
for (const [name, book] of Object.entries(books)) {
  for (const [k, v] of Object.entries(book)) {
    if (RECIPES[k]) throw new Error(`duplicate recipe ${k} (${name})`);
    RECIPES[k] = v;
  }
}
