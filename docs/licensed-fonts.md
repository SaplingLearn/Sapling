# Licensed fonts (Gummi)

Headings use **Gummi** (ZEKUTYPE, bought from fonts.xyz, order #20261108000001): Regular,
Italic and Bold, licensed for web use on **saplinglearn.com and any of its subdomains**.
Unlike the other faces in `frontend/src/app/fonts/` (Aleo, SUSE, IBM Plex Mono, Caveat — SIL
Open Font License 1.1), Gummi **may not be redistributed**, so its files are **not in this
repository**.

## Where the files live

R2 bucket **`sapling-licensed-fonts`** in the Saplinglearn Cloudflare account, served on the
custom domain **`fonts.saplinglearn.com`**:

| Object | Weight / style |
|---|---|
| `gummi/v1/Gummi-Regular.woff2` | 400 normal |
| `gummi/v1/Gummi-Italics.woff2` | 400 italic |
| `gummi/v1/Gummi-Bold.otf` | 700 normal |

Objects carry `Cache-Control: public, max-age=31536000, immutable`. To change a file, upload it
under a new prefix (`gummi/v2/…`) and bump `GUMMI_PREFIX` in `frontend/src/lib/licensedFonts.ts`;
never overwrite a `v1` object in place.

The bucket's **CORS rule is the licence boundary**. A browser only uses a cross-origin font when
the response allows its origin, and the rule allows exactly:

- `https://saplinglearn.com` (the `frontend` Worker)
- `https://staging.saplinglearn.com` (the `frontend-staging` Worker)
- `http://localhost:3000` (the local dev server)

A new licensed host (another `*.saplinglearn.com` subdomain) goes into both that rule
(`wrangler r2 bucket cors set sapling-licensed-fonts --file …`) and `LICENSED_HOST_RE` in
`licensedFonts.ts`.

## How a page gets them

`app/layout.tsx` renders `GUMMI_BOOT_SCRIPT` in `<head>`. On a licensed host it injects the three
`@font-face` rules, preloads Regular, and sets `--font-gummi` to Gummi (plus `--medium-stroke`,
which thickens 500 headings, since Gummi ships no medium). On **any other host** it does nothing:
`--font-gummi` keeps its `globals.css` default, **Aleo**, and no Gummi file is requested. That is
what keeps the font off hosts the licence doesn't cover:

- Worker Previews (`*-frontend-staging.saplinglearn.workers.dev`) and `*.workers.dev` URLs
- E2E slots (`127.0.0.1:310N`) — so Playwright and screenshots never depend on the network
- forks and anyone else's deploy of this code

Font stacks never name `'Gummi'` directly (`var(--font-gummi), Georgia, serif`): a bare family
name would make an unlicensed host fetch the file and log a CORS error.

## Rules

- Never commit a Gummi file to this repository (it is meant to be publishable), and never add
  one to `frontend/public/`.
- Only the three faces above are licensed. The original download also held SemiBold (and an
  earlier design handoff shipped Medium); neither is on the invoice, so don't use them without
  buying them first. A 600 Gummi heading renders Bold; a 500 one renders Regular plus the stroke.
