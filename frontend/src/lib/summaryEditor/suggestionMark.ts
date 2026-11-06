import { Mark, mergeAttributes } from "@tiptap/core";

export interface SuggestionMarkOptions {
  HTMLAttributes: Record<string, unknown>;
}

declare module "@tiptap/core" {
  interface Commands<ReturnType> {
    suggestionMark: {
      setSuggestionMark: (suggestionId: string) => ReturnType;
      unsetSuggestionMark: () => ReturnType;
    };
  }
}

/**
 * Highlights the ORIGINAL text of a pending AI suggestion (spec section 4:
 * "Pending AI edits render as a soft-bordered inline card ... rather than
 * a floating popover"). Removed via unsetSuggestionMark once the
 * suggestion is kept or undone — see SummaryEditor.tsx.
 */
export const SuggestionMark = Mark.create<SuggestionMarkOptions>({
  name: "suggestionMark",
  addOptions() {
    return { HTMLAttributes: {} };
  },
  addAttributes() {
    return {
      suggestionId: {
        default: null,
        parseHTML: (el) => el.getAttribute("data-suggestion-id"),
        renderHTML: (attrs) => ({ "data-suggestion-id": attrs.suggestionId }),
      },
    };
  },
  parseHTML() {
    return [{ tag: "span[data-suggestion-id]" }];
  },
  renderHTML({ HTMLAttributes }) {
    return [
      "span",
      mergeAttributes(this.options.HTMLAttributes, HTMLAttributes, {
        class: "summary-suggestion-pending",
      }),
      0,
    ];
  },
  addCommands() {
    return {
      setSuggestionMark:
        (suggestionId: string) =>
        ({ commands }) =>
          commands.setMark(this.name, { suggestionId }),
      unsetSuggestionMark:
        () =>
        ({ commands }) =>
          commands.unsetMark(this.name),
    };
  },
});
