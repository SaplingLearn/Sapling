# Sapling — New Frontend

A redesigned Next.js frontend for Sapling based on the `Sapling Rebuild` design prototype.

Visual system: warm paper neutrals, botanical green accent, serif display (Fraunces) + humanist sans (Inter), JetBrains Mono accents. Supports light/dark, accent themes (sage/forest/moss/ink/terracotta), density (compact/balanced/spacious), typography pairings, and three knowledge graph variants (orb/constellation/organism).

## Run

```bash
cd new_frontend
npm install
npm run dev     # http://localhost:3001
```

Backend rewrites go to `http://localhost:5000` by default (override via `BACKEND_URL`).

## Layout

- `src/app/` — App Router routes. The shell (sidebar + top bar) wraps every route except `auth` and `onboarding`, which are full-bleed.
- `src/components/` — shared UI primitives and per-screen components.
- `src/lib/data.ts` — mock data mirroring the design bundle. Swap for real API calls when wiring up.
- `src/lib/tweaks.tsx` — runtime design-token context (theme/accent/type/density/layout/graph).

## Routes

`/dashboard` `/learn` `/tree` `/study` `/library` `/calendar` `/social` `/achievements` `/settings` `/admin` — wrapped by the shell layout.

`/auth` `/onboarding` — full-bleed.

A floating Tweaks panel (bottom-left) lets you switch themes live. A Report button (bottom-right) opens the feedback modal.
