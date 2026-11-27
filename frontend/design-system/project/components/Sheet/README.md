# Sheet

A panel that slides in from the right over the page. For a decision that blocks the page use `Dialog`.

```tsx
import { Sheet } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `onClose` | `() => void` |  |  |
| `open` | `boolean` |  |  |
| `title` | `string` |  |  |
| `initialFocusRef`? | `RefObject<HTMLElement \| null>` |  |  |
| `side`? | `"right"` | `right` |  |
| `testid`? | `string` |  |  |
| `width`? | `number` | `480` | Panel width in px. Capped at the viewport by the stylesheet. |
| `zIndex`? | `number` | `100` |  |

## States

- Default
- Wide

Source: `frontend/src/components/ui/Sheet.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
