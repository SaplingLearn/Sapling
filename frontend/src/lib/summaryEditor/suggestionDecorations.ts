import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

export interface PendingSuggestionWidget {
  id: string;
  from: number;
  to: number;
  proposedText: string;
  onKeep: () => void;
  onUndo: () => void;
}

interface SuggestionDecorationsStorage {
  pending: PendingSuggestionWidget[];
}

const pluginKey = new PluginKey("summarySuggestionDecorations");

function buildSuggestionCard(suggestion: PendingSuggestionWidget): HTMLElement {
  const card = document.createElement("span");
  card.className = "summary-suggestion-card";
  card.contentEditable = "false";

  const proposed = document.createElement("span");
  proposed.className = "summary-suggestion-card__text";
  proposed.textContent = suggestion.proposedText;
  card.appendChild(proposed);

  const actions = document.createElement("span");
  actions.className = "summary-suggestion-card__actions";

  const keepBtn = document.createElement("button");
  keepBtn.type = "button";
  keepBtn.className = "btn btn--sm btn--primary";
  keepBtn.textContent = "Keep it";
  keepBtn.onclick = (e) => {
    e.preventDefault();
    suggestion.onKeep();
  };

  const undoBtn = document.createElement("button");
  undoBtn.type = "button";
  undoBtn.className = "btn btn--sm btn--ghost";
  undoBtn.textContent = "Undo this";
  undoBtn.onclick = (e) => {
    e.preventDefault();
    suggestion.onUndo();
  };

  actions.appendChild(keepBtn);
  actions.appendChild(undoBtn);
  card.appendChild(actions);
  return card;
}

/**
 * Extension whose `storage.pending` array the editor component mutates
 * directly, then forces a redraw of (via `editor.view.dispatch(editor.
 * state.tr)` — see SummaryEditor.tsx's `refreshSuggestionDecorations`).
 * This is the standard TipTap technique for decorations driven by state
 * that lives outside the document itself.
 */
export const SuggestionDecorations = Extension.create<Record<string, never>, SuggestionDecorationsStorage>({
  name: "summarySuggestionDecorations",
  addStorage() {
    return { pending: [] };
  },
  addProseMirrorPlugins() {
    const extensionStorage = this.storage;
    return [
      new Plugin({
        key: pluginKey,
        props: {
          decorations(state) {
            const decorations: Decoration[] = [];
            for (const suggestion of extensionStorage.pending) {
              if (suggestion.to > state.doc.content.size) continue;
              decorations.push(
                Decoration.inline(suggestion.from, suggestion.to, {
                  class: "summary-suggestion-pending-range",
                }),
              );
              decorations.push(
                Decoration.widget(suggestion.to, () => buildSuggestionCard(suggestion)),
              );
            }
            return DecorationSet.create(state.doc, decorations);
          },
        },
      }),
    ];
  },
});
