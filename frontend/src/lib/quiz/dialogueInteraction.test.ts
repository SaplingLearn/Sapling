import { describe, it, expect } from "vitest";
import {
  appendDialogueReply,
  asDialogueInteraction,
  decodeDialogueAnswer,
  dialogueMaxReplies,
  dialogueMinReplies,
  encodeDialogueAnswer,
  isDialogueComplete,
} from "./dialogueInteraction";
import type { DialogueInteraction } from "./types";

const FALL: DialogueInteraction = {
  kind: "dialogue",
  role: "Confused Classmate",
  open: "Heavier objects fall faster, right?",
  follow: "But the bowling ball is pulled harder. Doesn't a bigger force mean it falls faster?",
  placeholder: "Reply to your classmate",
  minReplies: 2,
  maxReplies: 4,
};

describe("asDialogueInteraction", () => {
  it("accepts a full partner script", () => {
    expect(asDialogueInteraction(FALL)).toEqual(FALL);
  });

  it("rejects missing role/open/follow and invalid bounds", () => {
    expect(asDialogueInteraction(undefined)).toBeNull();
    expect(
      asDialogueInteraction({
        kind: "dialogue",
        role: "",
        open: FALL.open,
        follow: FALL.follow,
      }),
    ).toBeNull();
    expect(
      asDialogueInteraction({
        kind: "dialogue",
        role: FALL.role,
        open: FALL.open,
        follow: FALL.follow,
        minReplies: 5,
        maxReplies: 2,
      }),
    ).toMatchObject({ minReplies: 2, maxReplies: 4 });
  });
});

describe("encode / decode / complete", () => {
  it("round-trips replies and gates Check at minReplies", () => {
    const encoded = encodeDialogueAnswer(["First", "Second"]);
    expect(decodeDialogueAnswer(encoded)).toEqual(["First", "Second"]);
    expect(isDialogueComplete(FALL, encoded)).toBe(true);
    expect(isDialogueComplete(FALL, encodeDialogueAnswer(["Only one"]))).toBe(false);
    expect(dialogueMinReplies(FALL)).toBe(2);
    expect(dialogueMaxReplies(FALL)).toBe(4);
  });

  it("appends until the max and ignores blank drafts", () => {
    expect(appendDialogueReply(FALL, [], "  hi  ")).toEqual(["hi"]);
    expect(appendDialogueReply(FALL, ["a"], "   ")).toEqual(["a"]);
    const full = ["1", "2", "3", "4"];
    expect(appendDialogueReply(FALL, full, "5")).toEqual(full);
  });
});
