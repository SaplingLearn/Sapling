// @vitest-environment jsdom
/**
 * One request writes a guide at a time. While one block is being regenerated,
 * nothing else that writes can be started from the reader.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

vi.mock("next/dynamic", async () => (await import("@/test-utils/mockNextDynamic")).mockNextDynamicModule());
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/context/UserContext", () => ({ useUser: () => ({ userId: "u1", userReady: true }) }));
vi.mock("@/components/chat/MarkdownChat", () => ({
  MarkdownChat: ({ children }: { children: string }) => <p>{children}</p>,
}));
vi.mock("@/lib/studyGuide/api", async importOriginal => ({
  ...(await importOriginal<typeof import("@/lib/studyGuide/api")>()),
  getGuide: vi.fn(),
  patchGuide: vi.fn(),
  generateGuide: vi.fn(),
  regenerateBlock: vi.fn(),
  answerCheck: vi.fn(),
}));

import { generateGuide, getGuide, regenerateBlock } from "@/lib/studyGuide/api";
import type { Block, GuideDetail } from "@/lib/studyGuide/types";

import { deferred, fixtureGuide, renderReader, sectionOf } from "./readerTestKit";

const mocks = {
  getGuide: vi.mocked(getGuide),
  generateGuide: vi.mocked(generateGuide),
  regenerateBlock: vi.mocked(regenerateBlock),
};

const REWRITTEN: Block = { type: "key_terms", id: "s2-i2", title: "Rewritten terms", terms: [] };

/** Open the reader and start rewriting the key-terms block. */
async function rewriting(guide: GuideDetail = fixtureGuide()) {
  const rewrite = deferred<{ block: Block }>();
  mocks.regenerateBlock.mockReturnValue(rewrite.promise);
  mocks.getGuide.mockResolvedValue(guide);
  renderReader();
  await screen.findByTestId("guide-title");
  const user = userEvent.setup();
  await user.click(screen.getByTestId("guide-block-regenerate-s2-i2"));
  return { user, rewrite };
}

beforeEach(() => vi.resetAllMocks());
afterEach(cleanup);

describe("while one block is being regenerated", () => {
  it("holds Update, Regenerate whole guide and every other block's Regenerate until it is back", async () => {
    const { user, rewrite } = await rewriting();
    expect(within(screen.getByTestId("guide-block-s2-i2")).getByRole("status")).toHaveTextContent("Regenerating this block");

    expect(screen.getByTestId("guide-update")).toBeDisabled();
    expect(screen.getByTestId("guide-block-regenerate-s1-i2")).toBeDisabled();
    expect(screen.getByTestId("guide-block-regenerate-s1-i6")).toBeDisabled();
    await user.click(screen.getByTestId("guide-menu"));
    expect(screen.getByTestId("guide-menu-regenerate")).toBeDisabled();

    // Nothing was sent that the server would turn away.
    await user.click(screen.getByTestId("guide-block-regenerate-s1-i2"));
    await user.click(screen.getByTestId("guide-update"));
    expect(mocks.regenerateBlock).toHaveBeenCalledTimes(1);
    expect(mocks.generateGuide).not.toHaveBeenCalled();

    await act(async () => rewrite.resolve({ block: REWRITTEN }));
    expect(within(screen.getByTestId("guide-block-s2-i2")).getByText("Rewritten terms")).toBeInTheDocument();
    expect(screen.getByTestId("guide-update")).toBeEnabled();
    expect(screen.getByTestId("guide-block-regenerate-s1-i2")).toBeEnabled();
    await user.click(screen.getByTestId("guide-menu"));
    expect(screen.getByTestId("guide-menu-regenerate")).toBeEnabled();
  });

  it("holds a failed section's Try again and the banner's Retry as well", async () => {
    const guide = fixtureGuide({ status: "failed" });
    Object.assign(sectionOf(guide, "s3"), { status: "failed", items: [] });
    await rewriting(guide);
    expect(screen.getByTestId("guide-section-retry-s3")).toBeDisabled();
    expect(screen.getByTestId("guide-generation-retry")).toBeDisabled();
  });
});
