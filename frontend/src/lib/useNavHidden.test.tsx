// @vitest-environment jsdom
import { describe, it, expect, vi, beforeEach } from "vitest";
import { renderHook } from "@testing-library/react";

const flagState = vi.hoisted(() => ({ flags: {} as Record<string, string>, ready: true }));
vi.mock("@/context/FlagsContext", () => ({ useFlagMap: () => flagState }));

import { useIsNavHidden } from "./useNavHidden";

const hidden = (path: string) => renderHook(() => useIsNavHidden()).result.current(path);

beforeEach(() => {
  flagState.flags = {};
  flagState.ready = true;
});

describe("useIsNavHidden", () => {
  it("a destination is hidden when its hide_* flag is on", () => {
    flagState.flags = { hide_library: "on", hide_study: "off" };
    expect(hidden("/library")).toBe(true);
    expect(hidden("/study")).toBe(false);
    expect(hidden("/calendar")).toBe(false);
  });

  it("matches a feature's own pages, whatever the query or hash", () => {
    flagState.flags = { hide_study: "on" };
    expect(hidden("/study?course=c1")).toBe(true);
    expect(hidden("/study/guide#top")).toBe(true);
    expect(hidden("/studying")).toBe(false);
  });

  it("the Dashboard, and a path that is no feature's, are never hidden", () => {
    flagState.flags = { hide_study: "on", hide_library: "on" };
    expect(hidden("/dashboard")).toBe(false);
    expect(hidden("/somewhere-else")).toBe(false);
  });

  it("nothing reads as hidden until the flags have loaded", () => {
    flagState.flags = { hide_library: "on" };
    flagState.ready = false;
    expect(hidden("/library")).toBe(false);
  });
});
