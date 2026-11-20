// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";

const loop = vi.hoisted(() => ({ status: null as boolean | "error" | null, ready: [] as boolean[] }));
vi.mock("@/components/learn/useLoopStatus", () => ({
  useLoopStatus: (_userId: string, ready: boolean) => {
    loop.ready.push(ready);
    return { status: ready ? loop.status : false, retry: () => {} };
  },
}));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("../Icon", () => ({ Icon: () => null }));

import { LearnNextCard, recommendationHref } from "./LearnNextCard";

const NAMED = { concept_name: "Graphs & Trees", reason: "builds on Recursion", node_id: "n7", course_id: "c1" };
const MAIN_LINK = "/learn?topic=Graphs%20%26%20Trees&mode=socratic";

beforeEach(() => {
  loop.status = null;
  loop.ready = [];
});
afterEach(cleanup);

describe("Learn next (#866 K05)", () => {
  it("with the loop on, starts the session on the recommended concept in its course", () => {
    loop.status = true;
    const navigate = vi.fn();
    render(<LearnNextCard recommendations={[NAMED]} navigate={navigate} />);
    fireEvent.click(screen.getByText("Graphs & Trees"));
    const params = new URLSearchParams(navigate.mock.calls[0][0].split("?")[1]);
    expect(params.get("concept")).toBe("n7");
    expect(params.get("course")).toBe("c1");
    expect(params.get("topic")).toBe("Graphs & Trees");
    expect(params.get("mode")).toBe("socratic");
  });

  it.each([false, "error", null] as const)("with the loop status %s, opens main's link byte for byte", (status) => {
    loop.status = status;
    const navigate = vi.fn();
    render(<LearnNextCard recommendations={[NAMED]} navigate={navigate} />);
    fireEvent.click(screen.getByText("Graphs & Trees"));
    expect(navigate).toHaveBeenCalledWith(MAIN_LINK);
  });

  it("reads no loop status when no recommendation names its concept (an older server)", () => {
    loop.status = true;
    const navigate = vi.fn();
    render(<LearnNextCard recommendations={[{ concept_name: "Graphs & Trees" }]} navigate={navigate} />);
    expect(loop.ready.every((r) => r === false)).toBe(true);
    fireEvent.click(screen.getByText("Graphs & Trees"));
    expect(navigate).toHaveBeenCalledWith(MAIN_LINK);
  });

  it("recommendationHref needs both the node and its course to name the concept", () => {
    expect(recommendationHref({ ...NAMED, course_id: null }, true)).toBe(MAIN_LINK);
    expect(recommendationHref({ ...NAMED, node_id: undefined }, true)).toBe(MAIN_LINK);
  });
});
