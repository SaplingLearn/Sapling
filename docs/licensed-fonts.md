# Licensed fonts (Gummi)

Headings use **Gummi** (ZEKUTYPE, bought from fonts.xyz). Unlike the other faces in
`frontend/src/app/fonts/` (Aleo, SUSE, IBM Plex Mono, Caveat — all SIL Open Font License),
Gummi is commercially licensed for saplinglearn.com and its subdomains and **may not be
redistributed**. This repository is public, so the font files are never committed here.

| Role | Face | Token |
|---|---|---|
| Headings, page titles, landing section heads | Gummi | `--font-display`, `FONT_DISPLAY`, `.font-gummi` |
| Long-form reading text (tutor answers, notes, journal) | Aleo | `--font-serif` |
| UI and body copy | SUSE | `--font-sans` |
| Numerals and code | IBM Plex Mono | `--font-mono` |

## Where the files live

The binaries live in the **private** repo `SaplingLearn/sapling-licensed-fonts` (`fonts/`).
Their SHA-256 hashes are pinned in `frontend/src/app/fonts/licensed-fonts.json`.

## How a build gets them

1. `frontend/scripts/fetch-licensed-fonts.mjs` runs before every build and dev server
   (`prebuild`, `predev`, and the `cf:*` scripts; `npm run fonts:fetch` runs it by hand).
   It downloads any missing or mismatched file using `LICENSED_FONTS_TOKEN`, checks the
   SHA-256, and writes it to the git-ignored `frontend/src/app/fonts/licensed/`.
2. `next.config.ts` (via `src/lib/licensedFonts.ts`) aliases `@gummi-font`:
   - all files present → `src/app/fonts/gummi.licensed.ts` (the real `next/font/local`);
   - files missing on an ordinary build (CI, E2E, a checkout without the token) →
     `src/app/fonts/gummi.fallback.ts`, and headings render in **Aleo**;
   - files missing on a **deploy** build (`WORKERS_CI=1`, set by Cloudflare Workers Builds,
     or `LICENSED_FONTS_REQUIRED=1`) → the build **fails**. A deploy never ships the stand-in.

| Variable | Where | Purpose |
|---|---|---|
| `LICENSED_FONTS_TOKEN` | Workers Builds build secret (frontend + frontend-staging); optionally your shell | Fine-grained GitHub token, **Contents: Read-only** on `sapling-licensed-fonts` only |
| `LICENSED_FONTS_REQUIRED` | optional | `1` makes a missing font fatal outside Workers Builds |
| `LICENSED_FONTS_REPO` / `LICENSED_FONTS_REF` | optional | Override the repo / branch from the manifest |

## Setup (once)

1. Create the private repo and push the three files (`Gummi-Regular.woff2`,
   `Gummi-Italics.woff2`, `Gummi-Bold.otf`) under `fonts/`.
2. Create a fine-grained personal access token: resource owner **SaplingLearn**, repository
   access **only** `sapling-licensed-fonts`, permission **Contents: Read-only**.
3. Cloudflare dashboard → Workers & Pages → **frontend** → Settings → Build →
   Build variables and secrets → add secret `LICENSED_FONTS_TOKEN`. Repeat for
   **frontend-staging**.
4. Locally, either export `LICENSED_FONTS_TOKEN` before `npm run dev`, or copy the three files
   into `frontend/src/app/fonts/licensed/` yourself.

## Changing a font file

Push the new file to the private repo and update its `sha256` in `licensed-fonts.json` in the
same Sapling PR. A hash mismatch is treated as a missing file (fatal on deploy builds).

## License notes

Order #20261108000001 (fonts.xyz): Gummi Regular, Bold and Italic, web use on
saplinglearn.com and any of its subdomains. The download also contained a SemiBold file that is
not on the invoice. It is not used.
