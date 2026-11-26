Sapling is a study companion for students: a knowledge graph of what you are learning, a tutor, quizzes and flashcards. The interface should feel like a thriving plant in a quiet library: alive and growing, but calm, steady and focused. Light mode only.

## Principles

- **Ground everything.** Surfaces are solid. No glass, no blur, no translucent panels.
- **Let white space breathe.** Negative space is part of the layout. Do not fill every gap.
- **Hierarchy through type, not decoration.** Use size, weight and spacing to lead the eye. Avoid rows of identical rounded cards with an icon, a heading and a line of body text.
- **Colour communicates.** Green means growth and mastery, amber means in progress, red means struggling. Never use a colour only to decorate.
- **Motion is slow and purposeful.** Entrances fade and rise a few pixels (`--dur` 220ms, `--ease`). Nothing bounces or flashes.

Do not use: gradient text, purple-to-blue gradients, neon or cyan accents, "AI-powered" pills with pulsing dots, a hero of one big number with a small label, or dark UI with glowing chrome.

## Colour

- Page background is `bg`; raised surfaces (cards, panels, dialogs, menus) are `bg-panel`; quiet fills and hover rows are `bg-subtle`; inputs use `bg-input`.
- Text is `text` for body and headings, `text-dim` for secondary lines, `text-muted` for hints and labels. All three pass 4.5:1 on `bg`, `bg-panel` and `bg-subtle`.
- Lines are `border`; use `border-strong` only where a control needs a visible edge.
- The brand green is `brand-forest`. It fills the primary action, with white text (7.4:1). `brand-forest-bright` is the brighter CTA and highlight fill and the `accent` role (focus, selected state). Do not invent new greens: use the `sap-*` ramp for tints.
- Status: `positive` and `state-mastery` for mastered or correct, `state-progress` for in progress, `state-struggle` for struggling, `warn`, `err` and `info` for messages, each with a `-soft` background for chips and banners.
- Course colours come from the ten `c-*` category hues. Grades use `grade-a` to `grade-f`.
- Public pages (landing, careers, news) use the cooler `moss-*`, `leaf-*` and `paper-*` palette instead of the warm `ink-*` ramp.
- Never write a hex value in a component. Every colour is a token.

## Type

- UI chrome is **SUSE** (`--font-sans`). Headings and brand moments are **Aleo** (`--font-display`, `--font-serif`), a slab serif. Long-form prose and the tutor's voice in chat are Aleo too. Code, ids and pasted tokens use the system monospace (`--font-code`). Labels and numbers stay in SUSE with tabular figures.
- Body text is 13px (`fs-md`) at line-height 1.5; the page default is 14px (`fs-base`). Chrome and labels run 10 to 12px (`fs-2xs`, `fs-xs`, `fs-sm`); body copy 14 to 16px; headings 18 to 26px; a screen title is 30px (`fs-4xl`); a display numeral 32px (`fs-5xl`). There are no other sizes.
- The production heading face is Gummi, licensed for saplinglearn.com only. It is not part of this system; Aleo stands in for it everywhere else.
- Write in sentence case. Labels are short and plain: "Upload notes", not "Upload Your Notes Now!".

## Space, radius, depth

- Spacing runs on a 4px step. The app's default density is compact: `pad-sm` 8px, `pad-md` 12px, `pad-lg` 16px, `pad-xl` 22px, rows 34px tall (`row-h`).
- Radii: `r-xs` 4px for small marks, `r-sm` 6px for buttons and fields, `r-md` 10px for menus, `r-lg` 16px for cards and dialogs, `r-xl` 22px for hero surfaces, `r-full` for pills.
- Shadows are faint and green-tinted: `shadow-sm` for resting cards, `shadow-md` for hover and popovers, `shadow-lg` for dialogs and menus. Every raised surface also has a `border`.

## Components

- Use the components in this system before building anything. In the codebase they live in `src/components/ui` and are styled with Tailwind classes on these tokens.
- One primary `Button` per surface. Text actions like Cancel and Done are `Button variant="link"`.
- Status labels are `Chip`; a custom-hue label (rarity, role, grade) is `Badge`.
- A view switch is `Toggle`; a choice inside a form is `SegmentedControl`; an on/off setting is `Switch`.
- A decision that blocks the page is a `Dialog`; help or details beside the page is a `Sheet`; a read-mostly list is a `PanelModal`. A list of actions is a `Menu`.
- An empty list or screen is an `EmptyState` that says what will appear and offers one action.

## Writing

- Speak to the student as "you". Be direct and warm, never cute.
- Say what happened and what to do next: "Couldn't upload that file. Try again.", not "Oops! Something went wrong."
- No emoji in the interface.
