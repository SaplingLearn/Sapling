# InlineBanner

A one-line message inside the page, above the content it is about, with optional actions on the right. Not for errors that block the page.

```tsx
import { InlineBanner } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `actions`? | `ReactNode` |  | Right-aligned controls. Usually a secondary button and a link button. |
| `testid`? | `string` |  |  |
| `tone`? | `"accent" \| "neutral"` | `accent` |  |

## States

- Accent
- Neutral
- With Actions

Source: `frontend/src/components/ui/InlineBanner.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
