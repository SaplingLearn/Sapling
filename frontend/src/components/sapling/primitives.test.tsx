// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import {
  BotanicalIcon,
  BOTANICAL_ASSETS,
  ChoiceGroup,
  GoalSummary,
  PageHeading,
  PhaseStrip,
  SaplingAction,
  SaplingSurface,
  SelectableRow,
  StatusMessage,
  stageIndexForPhase,
} from ".";

afterEach(cleanup);

describe("BotanicalIcon", () => {
  it("is decorative by default, so the parent control carries the name", () => {
    render(<button type="button" aria-label="Library"><BotanicalIcon name="library" /></button>);
    const icon = document.querySelector(".sapling-icon")!;
    expect(icon).toHaveAttribute("aria-hidden", "true");
    expect(icon).not.toHaveAttribute("role");
    expect(screen.getByRole("button", { name: "Library" })).toBeTruthy();
  });

  it("is a named image when it stands alone", () => {
    render(<BotanicalIcon name="clov" label="Clov" />);
    expect(screen.getByRole("img", { name: "Clov" })).toBeTruthy();
  });

  it("masks the exact approved file into a square box (aspect ratio kept by contain)", () => {
    render(<BotanicalIcon name="paper" size={24} />);
    const icon = document.querySelector<HTMLElement>(".sapling-icon")!;
    expect(icon.style.getPropertyValue("--sapling-icon-src")).toBe('url("/design/sapling/paper.svg")');
    expect(icon.style.width).toBe("24px");
    expect(icon.style.height).toBe("24px");
  });

  it("maps every name to an approved Pen export", () => {
    expect(Object.fromEntries(Object.entries(BOTANICAL_ASSETS).map(([k, v]) => [k, v.penNode]))).toEqual({
      today: "l2RIf", learn: "Q3Qtc5", library: "cPSOV", tutor: "eLW36",
      calendar: "tD2Nx", paper: "AHtpg", clov: "J19WJ2",
    });
  });
});

describe("SaplingSurface", () => {
  it("scopes tokens without adding a layout box", () => {
    render(<SaplingSurface testid="surface"><p>Inside</p></SaplingSurface>);
    const surface = screen.getByTestId("surface");
    expect(surface).toHaveClass("sapling-surface");
    expect(surface.style.display).toBe("contents");
  });
});

describe("PageHeading", () => {
  it("keeps course context out of the h1", () => {
    render(<PageHeading eyebrow="Course library" title="Good ideas start somewhere." description="Bring materials together." />);
    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Good ideas start somewhere.");
    expect(screen.getByRole("heading", { level: 1 })).not.toHaveTextContent("Course library");
  });
});

describe("SaplingAction", () => {
  it("is a native button that defaults to type=button and forwards its ref", () => {
    const ref = React.createRef<HTMLButtonElement>();
    const onClick = vi.fn();
    render(<SaplingAction ref={ref} onClick={onClick}>Upload material</SaplingAction>);
    const button = screen.getByRole("button", { name: "Upload material" });
    expect(button).toHaveAttribute("type", "button");
    expect(button).toHaveClass("btn", "sapling-action", "sapling-action--primary");
    expect(ref.current).toBe(button);
    fireEvent.click(button);
    expect(onClick).toHaveBeenCalledTimes(1);
  });
});

describe("SelectableRow", () => {
  it("states selection through aria-pressed, not colour alone", () => {
    const onClick = vi.fn();
    const { rerender } = render(<SelectableRow selected={false} onClick={onClick}>Recursion workshop</SelectableRow>);
    const row = screen.getByRole("button", { name: "Recursion workshop" });
    expect(row).toHaveAttribute("aria-pressed", "false");
    fireEvent.click(row);
    expect(onClick).toHaveBeenCalled();
    rerender(<SelectableRow selected onClick={onClick}>Recursion workshop</SelectableRow>);
    expect(row).toHaveAttribute("aria-pressed", "true");
    expect(row).toHaveAttribute("data-selected", "true");
  });
});

describe("ChoiceGroup", () => {
  const options = [
    { value: "C", letter: "C", label: "It calls itself with a smaller input." },
    { value: "A", letter: "A", label: "It repeats a block using a for loop." },
  ];

  it("is one named radio group in served order and reports the served value", () => {
    const onChange = vi.fn();
    render(<ChoiceGroup legend="What makes this recursive?" options={options} value={null} onChange={onChange} />);
    const group = screen.getByRole("group", { name: "What makes this recursive?" });
    const radios = within(group).getAllByRole("radio");
    expect(radios.map((r) => (r as HTMLInputElement).value)).toEqual(["C", "A"]);
    expect(new Set(radios.map((r) => (r as HTMLInputElement).name)).size).toBe(1);
    fireEvent.click(radios[1]);
    expect(onChange).toHaveBeenCalledWith("A");
  });

  it("marks the selected option as selected only, and locks while disabled", () => {
    render(<ChoiceGroup legend="Q" options={options} value="A" onChange={() => {}} disabled />);
    const radios = screen.getAllByRole("radio") as HTMLInputElement[];
    expect(radios[1].checked).toBe(true);
    expect(radios[1].closest("label")).toHaveAttribute("data-selected", "true");
    expect(radios[0].closest("label")).toHaveAttribute("data-selected", "false");
    for (const r of radios) expect(r).toBeDisabled();
    expect(document.body.textContent).not.toMatch(/correct/i);
  });
});

describe("GoalSummary", () => {
  it("is read-only unless the session allows edits AND a handler is given", () => {
    const { rerender } = render(<GoalSummary goal="Write recursive functions" scope="Functions + Recursion" />);
    expect(screen.getByRole("region", { name: "Your goal" })).toHaveTextContent("Scope: Functions + Recursion");
    expect(screen.queryByRole("button")).toBeNull();
    rerender(<GoalSummary goal="g" canEdit />);
    expect(screen.queryByRole("button")).toBeNull();
    const onEdit = vi.fn();
    rerender(<GoalSummary goal="g" canEdit onEdit={onEdit} />);
    fireEvent.click(screen.getByRole("button", { name: "Edit goal" }));
    expect(onEdit).toHaveBeenCalled();
  });
});

describe("PhaseStrip", () => {
  it("groups server phases the way LoopLearn does; hint is a check", () => {
    expect(["probe", "plan", "teach", "check", "feedback", "hint", "close"].map((p) => stageIndexForPhase(p as never)))
      .toEqual([0, 1, 2, 2, 2, 2, 3]);
    expect(stageIndexForPhase(null)).toBe(-1);
  });

  it("marks only the server's current stage, earlier ones completed, and offers no controls", () => {
    render(<PhaseStrip phase="check" testid="phases" />);
    const strip = screen.getByRole("list", { name: "Learning progress" });
    const items = within(strip).getAllByRole("listitem");
    expect(items.map((li) => li.getAttribute("aria-current"))).toEqual([null, null, "step", null]);
    expect(items[0]).toHaveTextContent("(completed)");
    expect(items[3]).toHaveTextContent("Wrap-up");
    expect(within(strip).queryByRole("button")).toBeNull();
    expect(within(strip).queryByRole("link")).toBeNull();
  });

  it("marks nothing current when the phase is unknown", () => {
    render(<PhaseStrip phase={null} />);
    expect(document.querySelector('[aria-current="step"]')).toBeNull();
  });
});

describe("StatusMessage", () => {
  it("announces errors as alerts with text and an operable retry", () => {
    const onRetry = vi.fn();
    render(<StatusMessage tone="error" title="Couldn't load your materials." onRetry={onRetry} testid="lib-error">Nothing was deleted.</StatusMessage>);
    const alert = screen.getByRole("alert");
    expect(alert).toHaveTextContent("Couldn't load your materials.");
    expect(alert).toHaveTextContent("Nothing was deleted.");
    fireEvent.click(screen.getByTestId("lib-error-retry"));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("uses a polite status for non-errors and disables retry while one runs", () => {
    render(<StatusMessage tone="pending" onRetry={() => {}} retrying>Scanning…</StatusMessage>);
    expect(screen.getByRole("status")).toHaveTextContent("Scanning…");
    expect(screen.getByRole("button", { name: "Retrying…" })).toBeDisabled();
  });

  it("offers no retry without a real retry path", () => {
    render(<StatusMessage tone="info">Saved.</StatusMessage>);
    expect(screen.queryByRole("button")).toBeNull();
  });
});
