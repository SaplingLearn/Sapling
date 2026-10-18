// @vitest-environment jsdom
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { GraphNode } from "@/lib/data";
import { NodeConnections } from "./NodeConnections";

const node = (id: string, name: string): GraphNode => ({
  id, name, subject: "Math", color: "green", course_id: "math",
  mastery_tier: "learning", mastery_score: 0.4,
});
const algebra = node("a", "Algebra");
const calculus = node("c", "Calculus");
afterEach(cleanup);

describe("NodeConnections", () => {
  it("shows the recorded relationship direction and opens the connected node by id", async () => {
    const onSelect = vi.fn();
    render(<NodeConnections node={calculus} nodes={[algebra, calculus]} edges={[
      { source: "a", target: "c", strength: 0.8, relationship_type: "prerequisite" },
    ]} onSelect={onSelect} />);
    const connection = screen.getByRole("button", { name: /Algebra.*Prerequisite.*Algebra → Calculus/ });
    await userEvent.click(connection);
    expect(onSelect).toHaveBeenCalledWith(algebra);
  });

  it("deduplicates undirected relevance edges without calling them prerequisites", () => {
    render(<NodeConnections node={calculus} nodes={[algebra, calculus]} edges={[
      { source: "a", target: "c", strength: 0.8 },
      { source: "c", target: "a", strength: 0.8, relationship_type: "related" },
    ]} onSelect={vi.fn()} />);
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(screen.getByText("Related")).toBeInTheDocument();
    expect(screen.queryByText(/Prerequisite/)).not.toBeInTheDocument();
  });

  it("ignores dangling edges, self links, and connections to other nodes", () => {
    render(<NodeConnections node={calculus} nodes={[algebra, calculus]} edges={[
      { source: "c", target: "missing", strength: 1 },
      { source: "c", target: "c", strength: 1 },
      { source: "a", target: "missing", strength: 1 },
    ]} onSelect={vi.fn()} />);
    expect(screen.getByText("No connections recorded yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("handles unknown relationship types without breaking the panel", () => {
    render(<NodeConnections node={calculus} nodes={[algebra, calculus]} edges={[
      { source: "a", target: "c", strength: 1, relationship_type: "constructor" },
    ]} onSelect={vi.fn()} />);
    expect(screen.getByRole("button", { name: /Connection.*Algebra → Calculus/ })).toBeInTheDocument();
  });
});
