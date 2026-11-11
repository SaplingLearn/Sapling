import { describe, it, expect } from "vitest";
import {
  layoutRowStyle,
  notesListRailStyle,
  noteDetailRailStyle,
  editorFrameStyle,
  chatRailStyle,
} from "./notetakerLayout";

// Each style is compared with key order included (Object.entries), since
// React writes inline style keys in object order.
const entries = (o: object) => Object.entries(o);

const RAIL_TRANSITION =
  "flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease)";

describe("layoutRowStyle", () => {
  it("normal", () => {
    expect(entries(layoutRowStyle(false))).toEqual(
      entries({
        flex: 1,
        minHeight: 0,
        display: "flex",
        gap: 16,
        padding: "32px 32px 24px",
        transition: "gap var(--dur-slow) var(--ease), padding var(--dur-slow) var(--ease)",
      }),
    );
  });

  it("fullscreen", () => {
    expect(layoutRowStyle(true)).toMatchObject({ gap: 24, padding: "24px 24px 24px 24px" });
  });
});

describe("side rails (list + detail)", () => {
  it("open normally with their own clamp() basis", () => {
    expect(entries(notesListRailStyle(false))).toEqual(
      entries({
        flex: "0 0 clamp(260px, 22%, 320px)",
        minWidth: 0,
        opacity: 1,
        overflow: "hidden",
        pointerEvents: undefined,
        transition: RAIL_TRANSITION,
      }),
    );
    expect(noteDetailRailStyle(false).flex).toBe("0 0 clamp(280px, 22%, 340px)");
    expect(noteDetailRailStyle(false).opacity).toBe(1);
  });

  it("collapse and ignore pointer events in fullscreen", () => {
    const collapsed = {
      flex: "0 0 0px",
      minWidth: 0,
      opacity: 0,
      overflow: "hidden",
      pointerEvents: "none",
      transition: RAIL_TRANSITION,
    };
    expect(entries(notesListRailStyle(true))).toEqual(entries(collapsed));
    expect(entries(noteDetailRailStyle(true))).toEqual(entries(collapsed));
  });
});

describe("editorFrameStyle", () => {
  it("is unbounded normally and capped in fullscreen", () => {
    expect(entries(editorFrameStyle(false))).toEqual(
      entries({
        width: "100%",
        maxWidth: "none",
        display: "flex",
        transition: "max-width var(--dur-slow) var(--ease)",
      }),
    );
    expect(editorFrameStyle(true).maxWidth).toBe("min(1200px, 96%)");
  });
});

describe("chatRailStyle", () => {
  const transition =
    "flex-basis var(--dur-slow) var(--ease), opacity var(--dur) var(--ease), padding var(--dur-slow) var(--ease)";

  it("is collapsed normally", () => {
    expect(entries(chatRailStyle(false))).toEqual(
      entries({
        flex: "0 0 0px",
        minWidth: 0,
        opacity: 0,
        overflow: "hidden",
        pointerEvents: "none",
        display: "flex",
        flexDirection: "column",
        paddingTop: 0,
        paddingBottom: 0,
        transition,
      }),
    );
  });

  it("opens in fullscreen", () => {
    expect(entries(chatRailStyle(true))).toEqual(
      entries({
        flex: "0 0 clamp(300px, 24%, 380px)",
        minWidth: 0,
        opacity: 1,
        overflow: "hidden",
        pointerEvents: undefined,
        display: "flex",
        flexDirection: "column",
        paddingTop: 32,
        paddingBottom: 32,
        transition,
      }),
    );
  });
});
