# AnswerOption

One multiple-choice answer row. Lives inside a `role="radiogroup"` that owns the roving tab stop. After marking, the chosen row shows `status`.

```tsx
import { AnswerOption } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `letter` | `string` |  |  |
| `state` | `"default" \| "selected" \| "correct" \| "chosen-wrong" \| "muted"` |  |  |
| `text` | `string` |  |  |
| `checked`? | `boolean` | `state === "selected" \|\| state === "chosen-wrong"` | Whether this is the row the student picked. Defaults to what `state` says; pass it where a pick can also be `correct`, which on its own only marks the right answer. |
| `disabled`? | `boolean` | `false` |  |
| `onSelect`? | `(() => void)` |  |  |
| `status`? | `string` |  | A visible word beside the mark once the answer is marked ("Correct", "Incorrect") — on the row the student chose, so the result sits on the answer itself. Decorative: the accessible name already carries it. |
| `tabIndex`? | `number` |  | Roving tab stop, owned by the enclosing radiogroup. |
| `testid`? | `string` |  |  |

## States

- Default
- Selected
- Correct
- Chosen Wrong
- Muted
- Disabled
- Marked Question

Source: `frontend/src/components/ui/AnswerOption.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
