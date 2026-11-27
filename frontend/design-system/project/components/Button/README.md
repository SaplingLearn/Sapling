# Button

Every action button. `secondary` is the default; `primary` for the one main action on a surface; `link` for text actions like Cancel or Done. Pills and segmented choices are `Toggle`, not Button.

```tsx
import { Button } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `size`? | `"sm" \| "md" \| "lg" \| "xl"` | `md` |  |
| `variant`? | `"primary" \| "secondary" \| "ghost" \| "danger" \| "link"` | `secondary` |  |

## States

- Secondary
- Primary
- Ghost
- Danger
- Link
- Link Pressed
- Disabled
- Sizes

Source: `frontend/src/components/ui/Button.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
