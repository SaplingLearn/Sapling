# SegmentedControl

One choice from a short fixed set inside a form or panel (a radio group with arrow-key movement). For a view switch in a toolbar use `Toggle`.

```tsx
import { SegmentedControl } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `onChange` | `(v: V) => void` |  |  |
| `options` | `{ value: V; label: string; disabled?: boolean \| undefined; }[]` |  |  |
| `value` | `string \| number` |  |  |
| `ariaLabel`? | `string` |  |  |
| `labelledBy`? | `string` |  |  |
| `testid`? | `string` |  |  |

## States

- Default
- With Disabled Option

Source: `frontend/src/components/ui/SegmentedControl.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
