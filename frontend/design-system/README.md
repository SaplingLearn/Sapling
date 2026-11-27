# Sapling design system

`project/` is Sapling's design system as Claude Design reads it: tokens, fonts, the app's compiled CSS, and a preview plus guidelines for every component in `src/components/ui`. It is generated from the code and committed, so every change to it is reviewed in a PR.

Published as the **Sapling** design system artifact: https://claude.ai/artifact/C3MEhkiE25fn9dgtZtiMcp (private until shared from its page). Its page is read-only (`"editing": "code"`): change the code, not the page.

## What comes from where

| In `project/` | From |
| --- | --- |
| `tokens.json`, `tokens.css` | `src/styles/tokens.css` and `theme.css` (`scripts/design-system/tokens.mjs`) |
| `fonts/`, `licenses/` | `src/app/fonts` (Aleo, SUSE; OFL). Gummi is licensed for saplinglearn.com only and is never included. |
| `components/bundle.css` | The app's compiled stylesheet, from the Storybook build |
| `components/<Name>/preview.html` | A static render of every Storybook story of that component |
| `components/<Name>/README.md` | The story's `docs.description.component` and the component's prop types |
| `README.md` | `brand.md` (written by hand: the brand book) |
| `components/Cover/preview.html` | `cover.html` (by hand) |
| Logos | Uploaded to the artifact once; their ids are in `assets.json` |

## Regenerate

```
npm run design-system                                   # builds Storybook, then writes project/
node scripts/design-system/render-previews.mjs /tmp/ds  # optional: screenshots of every preview as the page frames it
```

Commit `project/` in the same PR as the change that caused it. CI's "Design system is regenerated" check (`.github/workflows/design-system.yml`) fails a PR that changes components, stories, tokens, fonts or the generator without touching `project/`.

## Publish

A Claude scheduled task runs the Trov prompt `sapling-design-system-sync` (SaplingLearn org, Prompt Library) every day. It compares the artifact with main and publishes only when main is ahead, so a merged change reaches Claude Design within a day. To publish right away, run the same prompt in any Claude session. The repo stays the source of truth either way.

## Add a component

1. Build it in `src/components/ui` and export it from `index.ts`.
2. Add `<Name>.stories.tsx` beside it: a `docs.description.component` whose first sentence says what it is for, and a story per variant and state.
3. Run `npm run design-system` and commit `project/`.

## Use it in Claude Design

Pick **Sapling** as the design system (mark it the default from its page so new designs use it without asking). Designs come out in the classes and tokens the previews show; bring one into the app by building it from `components/ui`, adding stories for anything new, and regenerating.
