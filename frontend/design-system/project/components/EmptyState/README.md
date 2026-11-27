# EmptyState

What a list or screen shows when it has nothing yet. Say what will appear and how to get it, with one action.

```tsx
import { EmptyState } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `title` | `string` |  |  |
| `action`? | `{ label: string; href: string; } \| ReactNode` |  | A link out, or any control the caller would rather build itself. |
| `body`? | `string` |  |  |
| `eyebrow`? | `string` |  | Mono/uppercase line above the title. |
| `icon`? | `string` |  | Name from `components/Icon`. |
| `size`? | `"md" \| "hero"` | `md` |  |
| `testid`? | `string` |  |  |

## States

- Default
- With Link Action
- With Button Action
- With Eyebrow
- Hero
- Title Only

Source: `frontend/src/components/ui/EmptyState.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
