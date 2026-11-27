# Toggle

A row of pill buttons where one is pressed. Use for view switches and filters with a few options. For a form-style choice inside a panel use `SegmentedControl`; for an on/off setting use `Switch`.

```tsx
import { Toggle } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `onChange` | `(v: T) => void` |  |  |
| `options` | `{ value: T; label: ReactNode; title?: string \| undefined; }[]` |  |  |
| `value` | `string` |  |  |
| `labelledBy`? | `string` |  | The id of the row's visible label: the row is then a group named by it, so a screen reader says what the pressed option is a choice of. |
| `size`? | `"sm" \| "md"` | `md` |  |
| `testid`? | `string` |  | Container testid; each option gets `${testid}-${value}`. |

## States

- Medium
- Small
- Second Selected

Source: `frontend/src/components/ui/Toggle.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
