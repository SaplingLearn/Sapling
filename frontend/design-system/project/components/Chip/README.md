# Chip

Short status labels and tags. Pick the variant by meaning: `accent` good or active, `warn` needs attention, `err` failed, `info` neutral news. For a custom hue (rarity, role, grade) use `Badge`.

```tsx
import { Chip } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `icon`? | `ReactNode` |  |  |
| `variant`? | `"neutral" \| "accent" \| "warn" \| "err" \| "info"` | `neutral` |  |

## States

- Neutral
- Accent
- Warn
- Err
- Info
- With Icon
- All Variants

Source: `frontend/src/components/ui/Chip.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
