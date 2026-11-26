# PanelModal

A read-mostly modal: a sticky header with a label and Close, over a scrolling body. Rendered only while open.

```tsx
import { PanelModal } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `label` | `string` |  |  |
| `onClose` | `() => void` |  |  |
| `maxHeight`? | `string` | `max-h-[82vh]` | Tailwind max-height class for the panel. |
| `maxWidth`? | `string` | `max-w-160` | Tailwind max-width class for the panel, e.g. "max-w-160". |
| `zIndex`? | `number` | `120` |  |

## States

- Default

Source: `frontend/src/components/ui/PanelModal.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
