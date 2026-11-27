# ProgressDots

Where the student is in a sequence of questions. `outcomes` colours marked dots; `onSelect` makes each dot a numbered button that jumps to its item.

```tsx
import { ProgressDots } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `answered` | `number` |  | How many items are answered — contiguous from 0. Ignored when `done` is given. |
| `ariaLabel` | `string` |  |  |
| `current` | `number` |  | 0-based index of the item being worked on. |
| `total` | `number` |  |  |
| `disabled`? | `boolean` | `false` | With `onSelect`: the buttons show but can't be pressed right now. |
| `done`? | `readonly boolean[]` |  | Per item: answered or not — for a sequence answered out of order, where "answered" is not a prefix. |
| `onSelect`? | `((index: number) => void)` |  | Makes each dot a numbered button that jumps to its item. |
| `orientation`? | `"column" \| "row"` | `column` |  |
| `outcomes`? | `readonly (boolean \| null)[]` |  | Per dot: true = answered correctly, false = incorrectly, null/absent = not marked (or the verdict is being held back). Colours the dot. |
| `testid`? | `string` |  |  |

## States

- Row
- Column
- Start
- With Outcomes
- Navigable
- Navigable Disabled

Source: `frontend/src/components/ui/ProgressDots.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
