# Feature · Profile & Cosmetics (Cross-Cutting)

> Covers: `Avatar`, `AvatarFrame`, `NameColorRenderer`, `TitleFlair`, `RoleBadge`, `ProfileBanner` — the cross-cutting identity/cosmetic primitives used by Navbar, Settings, Room overviews, Member lists, and Achievement showcases.

---

## 1. Overview

Sapling's identity system has five visual surfaces:

1. **Avatar** — the user's picture (or initials fallback on a deterministic color).
2. **AvatarFrame** — a decorative ring (PNG overlay) rendered on top of the avatar. Transparent when no frame equipped.
3. **NameColorRenderer** — renders a name with a solid color or CSS gradient (including `background-clip: text` when `cssValue` contains "gradient").
4. **TitleFlair** — a rarity-colored pill with a short title string (e.g., "Top Scholar").
5. **RoleBadge** — a role pill with the role's own color + optional icon (for admin / moderator-style affordances).

All are thin presentational components. Their data comes from `UserContext.equippedCosmetics` (populated by `/api/auth/me`) or from a `UserProfile` returned by `fetchPublicProfile`.

`ProfileBanner` is a sixth component but appears to be **dead code**: no importers in `src/` (Grep confirms). Covered for completeness.

---

## 2. Component contracts

### 2.1 `Avatar` (`src/components/Avatar.tsx`, 45 lines)

```ts
interface Props {
  userId: string;  // seeds color for the initials fallback
  name: string;    // initials derived from this
  size?: number;   // default 32
  avatarUrl?: string; // if present, renders an <img>; else initials
  className?: string;
}
```

- Image path: `<img src avatarUrl alt=name referrerPolicy="no-referrer">`. The `no-referrer` is key — Google profile images 403 without it.
- Fallback: a circle with `background: getAvatarColor(userId)` and `getInitials(name)` centered. Both helpers in `lib/avatarUtils.ts`.
- Font size scales with avatar size: `Math.max(10, Math.floor(size * 0.33))`.

### 2.2 `AvatarFrame` (`src/components/AvatarFrame.tsx`, 45 lines)

Stacks a `<img>` frame overlay on top of `Avatar`:

```ts
interface Props {
  frameUrl?: string;      // overlay PNG (transparent)
  frameSlug?: string;     // unused currently
  userId, name, size, avatarUrl, className;  // forwarded to Avatar
}
```

- If no `frameUrl`, falls back to plain `Avatar`.
- Otherwise: `position: relative` container, `<Avatar>` underneath, `<img>` overlay with `inset: 0; pointer-events: none; object-fit: contain`.
- `frameSlug` prop is declared but unused — dead prop.

### 2.3 `NameColorRenderer` (`src/components/NameColorRenderer.tsx`, 32 lines)

```ts
interface Props { name: string; cssValue?: string; }
```

Three render paths:
1. No `cssValue` → `<span style={{ color: var(--text) }}>{name}</span>`.
2. `cssValue.includes('gradient')` → use `background: cssValue; -webkit-background-clip: text; color: transparent`.
3. Otherwise → `<span style={{ color: cssValue }}>{name}</span>` (solid CSS color).

### 2.4 `TitleFlair` (`src/components/TitleFlair.tsx`, 43 lines)

```ts
interface Props { title: string; rarity: RarityTier; }
```

- Rarity → CSS vars (`--rarity-common` through `--rarity-legendary`, plus `-bg` variants).
- Renders a pill with border + background + text color all from the rarity.

### 2.5 `RoleBadge` (`src/components/RoleBadge.tsx`, 45 lines)

```ts
interface Props {
  role: Role; // {name, color, icon?, description?}
  size?: 'sm' | 'md';
}
```

- Uses CSS `color-mix(in srgb, ${color} 10%, transparent)` for background — requires a modern browser (Chrome 111+, Firefox 113+, Safari 16.2+).
- Native `title` attribute for `role.description` (accessibility via browser tooltip).
- Optional role.icon as a small `<img>`.

### 2.6 `ProfileBanner` (`src/components/ProfileBanner.tsx`, 37 lines) — dead code

```ts
interface Props { bannerUrl?: string; }
```

Renders either a banner image or a default gradient fallback. 160px tall, `border-radius: var(--radius-md)`. No importers. Originally intended for `/profile/:userId` which doesn't exist (QUESTIONS Q10).

---

## 3. Where each is used

| Component | Used by |
|---|---|
| `Avatar` | `AvatarFrame`, `RoomChat` (message bubbles), `RoomMembers`, various inline |
| `AvatarFrame` | `Navbar` user-menu, `Settings` profile section, `CosmeticsManager` preview, profile-preview modal |
| `NameColorRenderer` | `Settings` profile section, `CosmeticsManager` preview, profile-preview modal |
| `TitleFlair` | Same as NameColorRenderer |
| `RoleBadge` | `Admin` users table, `Settings` profile section |
| `ProfileBanner` | **no importers** (dead) |

Grep for the canonical usage locations if you're consolidating these.

---

## 4. Identity data flow

```
GET /api/auth/me
  → UserContext.equippedCosmetics
    = { avatar_frame?: {asset_url}, banner?: {asset_url}, name_color?: {css_value}, title?: {name, rarity}, featured_role?: Role }
  → UserContext.featuredRole
  → UserContext.isAdmin
  → UserContext.roles
```

Equipping / unequipping: `CosmeticsManager` calls `equipCosmetic(userId, slot, cosmeticId | null)` then `refreshProfile()`, which re-runs `fetchProfileData` and propagates new cosmetics into every consumer of `useUser()`.

---

## 5. Edge cases

1. **`referrerPolicy="no-referrer"`** on avatar images is crucial for Google CDN images. Drop it and Google returns 403 Forbidden, avatars break silently.
2. **`color-mix`** CSS function in `RoleBadge` requires modern browsers — no polyfill.
3. **`background-clip: text` + gradient** in `NameColorRenderer` requires `-webkit-` prefix — included. Fine in all current browsers.
4. **Dead code**: `ProfileBanner` is unused. `frameSlug` prop on `AvatarFrame` is unused.
5. **Size consistency**: `AvatarFrame` and `Avatar` both accept `size?: number` with default 32. Consumers pass 28 / 48 / 64. Rebuild should formalize a token set (sm/md/lg) to avoid ad-hoc numbers.
6. **Frames must be PNGs with transparent middle.** If someone uploads a frame with a colored center, it occludes the avatar. No frontend validation.
7. **No lazy loading** on cosmetic assets — every `AvatarFrame` loads the overlay image immediately.

---

## 6. CSS tokens the rebuild must preserve or re-derive

From `globals.css` (not yet audited; inferred from usage):

- `--rarity-common`, `--rarity-uncommon`, `--rarity-rare`, `--rarity-epic`, `--rarity-legendary` — text/border colors per rarity.
- `--rarity-*-bg` — muted fills per rarity.
- `--radius-sm`, `--radius-md`, `--radius-full` — pill + card radii.
- `--text`, `--text-dim`, `--text-muted`, `--text-secondary`, `--text-placeholder` — the full text hierarchy.
- `--accent`, `--accent-border`, `--accent-dim`, `--accent-active`, `--accent-glow` — the Sapling green.
- `--bg`, `--bg-panel`, `--bg-subtle`, `--bg-input`, `--bg-topbar` — surface colors.
- `--dur-fast`, `--dur-base` — animation timings.
- `--shadow-sm`, `--shadow-md` — card elevations.

These will be enumerated in `docs/frontend-audit/02-components.md` during Phase 4.

---

## 7. Things to preserve in the rebuild

- `Avatar` with `referrerPolicy="no-referrer"` and initials fallback on a seeded color.
- Layered `AvatarFrame` pattern (PNG overlay on top of avatar).
- Solid **and** gradient support in `NameColorRenderer` (with `background-clip: text` for gradients).
- Rarity tier tokens driving all of `TitleFlair`, `AchievementCard`, `AchievementUnlockToast`.
- `RoleBadge` with `color-mix` translucent background.
- The full cosmetic lifecycle (`fetchCosmetics` → display grid → `equipCosmetic(slot, id|null)` → `refreshProfile`).

## 8. Things to rework

- Remove `ProfileBanner.tsx` (dead) or re-introduce a public profile page that uses it.
- Remove unused `frameSlug` prop on `AvatarFrame`.
- Standardize avatar size tokens (replace magic numbers 28/32/48/64 with `sm/md/lg/xl`).
- Add frontend validation for cosmetic image uploads (required transparency for frames).
- Add lazy loading / `loading="lazy"` to cosmetic `<img>` overlays.
