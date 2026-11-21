// @vitest-environment jsdom
/**
 * Every insertable block, and the one property that actually matters about
 * them: a block that is saved as `innerHTML` and read back must come back the
 * same, still driven by the editor's delegated handlers.
 *
 * That is what `data-act`, `data-blk` and the VALUE ATTRIBUTE on each input
 * are for — a React component would not survive the round trip, markup does.
 */
import { describe, expect, it } from "vitest";

import { BLOCKS, BLOCK_MENU, GRAPH_KINDS, det, matrixOutput } from "./blocks";
import { graphHTML } from "./useNoteGraphs";

/** Parse a block's HTML the way the editor stores and restores it. */
function roundTrip(html: string): HTMLElement {
  const first = document.createElement("div");
  first.innerHTML = html;
  // Saved as a string, read back as a string: exactly what the API does.
  const second = document.createElement("div");
  second.innerHTML = first.innerHTML;
  expect(second.innerHTML).toBe(first.innerHTML);
  return second;
}

describe("every block survives being stored as HTML", () => {
  const cases: [string, string][] = [
    ["math", BLOCKS.math("x^2")],
    ["matrix", BLOCKS.matrix(2)],
    ["table", BLOCKS.table()],
    ["checklist", BLOCKS.check()],
    ["toggle", BLOCKS.toggle()],
    ["practice question", BLOCKS.qa()],
    ["flashcard", BLOCKS.card()],
    ["code", BLOCKS.code()],
    ["divider", BLOCKS.divider()],
    ["graph", graphHTML({ kind: "fn" })],
    ["bar chart", graphHTML({ kind: "bar" })],
    ["pie chart", graphHTML({ kind: "pie" })],
  ];

  it.each(cases)("%s round-trips byte for byte", (_name, html) => {
    roundTrip(html);
  });

  /**
   * Two blocks have no `data-act` button, and both are right: a divider is an
   * `<hr>` with nothing to drive, and an equation is opened by clicking the
   * equation itself rather than a control beside it.
   */
  const NO_ACTIONS = new Set(["divider", "math"]);

  it.each(cases)("%s keeps something for the editor to act on", (name, html) => {
    const el = roundTrip(html);
    if (NO_ACTIONS.has(name)) {
      expect(el.querySelector("hr, .math"), `${name}`).toBeTruthy();
      return;
    }
    expect(el.querySelector("[data-act]"), `${name} has no action`).toBeTruthy();
  });

  it("each block leaves a paragraph after it, so there is somewhere to type", () => {
    for (const [name, html] of cases) {
      // The design's checklist is a bare `<ul>`: a list grows by pressing
      // Enter in its last item, so it needs no paragraph after it.
      if (name === "checklist") continue;
      const el = roundTrip(html);
      expect(el.lastElementChild?.tagName, name).toBe("P");
    }
  });

  it("the checklist is the bare list the design ships", () => {
    const el = roundTrip(BLOCKS.check());
    expect(el.children).toHaveLength(1);
    expect(el.firstElementChild?.tagName).toBe("UL");
  });
});

describe("the matrix calculator", () => {
  it("computes a 2×2 and a 3×3 determinant", () => {
    expect(det([3, 1, 2, 4])).toBe(10);
    expect(det([2, 0, 1, 1, 3, 2, 1, 1, 1])).toBe(0);
  });

  it("says what a determinant means, in the design's words", () => {
    expect(matrixOutput(["3", "1", "2", "4"])).toEqual({
      out: "det = <b>10</b>",
      note: "Invertible. Scales area by 10.",
    });
    expect(matrixOutput(["2", "0", "1", "1", "3", "2", "1", "1", "1"]).note)
      .toBe("Zero determinant: not invertible, columns are dependent.");
    expect(matrixOutput(["1", "0", "0", "-1"]).note)
      .toBe("Invertible. Scales area by 1 and flips orientation.");
  });

  it("asks for the missing entries rather than showing NaN", () => {
    expect(matrixOutput(["3", "", "2", "4"])).toEqual({
      out: "det = <b>?</b>",
      note: "Fill every entry.",
    });
  });

  it("writes its entries as attributes, so they survive a save", () => {
    const el = roundTrip(BLOCKS.matrix(2));
    const inputs = [...el.querySelectorAll<HTMLInputElement>(".mx-grid input")];
    expect(inputs).toHaveLength(4);
    expect(inputs.map(i => i.getAttribute("value"))).toEqual(["3", "1", "2", "4"]);
  });
});

describe("the table", () => {
  it("opens with a head and two rows, and an edit mode that starts off", () => {
    const el = roundTrip(BLOCKS.table());
    expect(el.querySelectorAll("thead th")).toHaveLength(3);
    expect(el.querySelectorAll("tbody tr")).toHaveLength(2);
    expect(el.querySelector('[data-blk="table"]')?.getAttribute("data-edit")).toBe("0");
  });

  it("takes the heads and rows it is given", () => {
    const el = roundTrip(BLOCKS.table(["Op", "Effect"], [["Swap", "Flips the sign"]]));
    expect(el.querySelector("th")?.textContent).toBe("Op");
    expect(el.querySelector("td")?.textContent).toBe("Swap");
  });

  it("offers every row and column control", () => {
    const el = roundTrip(BLOCKS.table());
    const acts = [...el.querySelectorAll("[data-act]")].map(b => b.getAttribute("data-act"));
    expect(acts).toEqual(expect.arrayContaining(["row", "col", "delrow", "delcol", "tedit"]));
  });
});

describe("the checklist, toggle, question and flashcard", () => {
  it("a checklist item starts unticked and carries its box", () => {
    const el = roundTrip(BLOCKS.check(["Why does a row swap flip the sign?"]));
    const li = el.querySelector("li")!;
    expect(li.getAttribute("data-done")).toBe("0");
    expect(li.querySelector('[data-act="check"]')).toBeTruthy();
    expect(li.textContent).toContain("Why does a row swap flip the sign?");
  });

  it("a toggle opens expanded, as the design draws it", () => {
    const el = roundTrip(BLOCKS.toggle("Worked example", "Expand along the first row."));
    expect(el.querySelector(".blk")?.getAttribute("data-open")).toBe("1");
    expect(el.querySelector(".tg-title")?.textContent).toBe("Worked example");
  });

  it("a practice question hides its answer until it is asked for", () => {
    const el = roundTrip(BLOCKS.qa("What is det(2A)?", "2³ · 4 = 32."));
    expect(el.querySelector(".blk")?.getAttribute("data-open")).toBe("0");
    expect(el.querySelector(".qa-a")?.textContent).toBe("2³ · 4 = 32.");
    expect(el.querySelector('[data-act="open"]')?.textContent).toBe("Show Answer");
  });

  it("a flashcard has two faces and starts front up", () => {
    const el = roundTrip(BLOCKS.card("det(A)", "How A scales area"));
    expect(el.querySelector(".blk")?.getAttribute("data-open")).toBe("0");
    expect(el.querySelector(".fc-front")?.textContent).toBe("det(A)");
    expect(el.querySelector(".fc-back")?.textContent).toBe("How A scales area");
  });
});

describe("equations", () => {
  it("an equation stores its LaTeX and is not editable as text", () => {
    const el = roundTrip(BLOCKS.math("\\det(AB) = \\det(A)\\,\\det(B)"));
    const math = el.querySelector(".math")!;
    expect(math.getAttribute("data-tex")).toBe("\\det(AB) = \\det(A)\\,\\det(B)");
    expect(math.getAttribute("contenteditable")).toBe("false");
  });

  it("an empty one is still a block, so the palette has something to fill", () => {
    const el = roundTrip(BLOCKS.math());
    expect(el.querySelector(".math")?.getAttribute("data-tex")).toBe("");
  });

  it("escapes a tex string rather than letting it break the markup", () => {
    const el = roundTrip(BLOCKS.math('a" onload="x'));
    expect(el.querySelector(".math")?.getAttribute("data-tex")).toBe('a" onload="x');
    expect(el.querySelector("[onload]")).toBeNull();
  });
});

describe("the graph block", () => {
  it("opens as a function plot with the design's two expressions", () => {
    const el = roundTrip(graphHTML({ kind: "fn" }));
    const inputs = [...el.querySelectorAll<HTMLInputElement>(".pl-expr")];
    expect(inputs.map(i => i.getAttribute("value"))).toEqual(["x^2 - 2x - 3", "(1, -4)"]);
  });

  it("a chart opens with its kind's own data", () => {
    const el = roundTrip(graphHTML({ kind: "bar" }));
    expect(el.querySelector<HTMLInputElement>(".ch-title")?.getAttribute("value"))
      .toBe("Study Hours");
    expect(el.querySelectorAll(".ch-row")).toHaveLength(5);
  });

  it("carries its view, so a pan and a zoom survive a reload", () => {
    const el = roundTrip(graphHTML({ kind: "fn", view: "2,-1,0.05" }));
    expect(el.querySelector(".gx")?.getAttribute("data-view")).toBe("2,-1,0.05");
  });

  it("offers all five kinds, with the chosen one marked", () => {
    const el = roundTrip(graphHTML({ kind: "pie" }));
    const buttons = [...el.querySelectorAll('[data-act="g-kind"]')];
    expect(buttons).toHaveLength(GRAPH_KINDS.length);
    expect(buttons.find(b => b.classList.contains("on"))?.getAttribute("data-k")).toBe("pie");
  });

  it("a finalized graph says so, so it reloads read-only", () => {
    const el = roundTrip(graphHTML({ kind: "fn", final: true }));
    expect(el.querySelector(".gx")?.getAttribute("data-final")).toBe("1");
  });
});

describe("the Insert menu", () => {
  it("lists the design's nine blocks, each with a glyph and a description", () => {
    expect(BLOCK_MENU).toHaveLength(9);
    for (const item of BLOCK_MENU) {
      expect(item.label).toBeTruthy();
      expect(item.desc).toBeTruthy();
      expect(item.glyph).toBeTruthy();
      expect(item.html()).toContain("<");
    }
  });

  it("every item it offers actually builds a block", () => {
    for (const item of BLOCK_MENU) {
      const el = roundTrip(item.html());
      expect(el.children.length, item.label).toBeGreaterThan(0);
    }
  });
});
