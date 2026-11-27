# FilterPills

Filter a list by one category, with an optional colour dot per option.

```tsx
import { FilterPills } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `onChange` | `(v: T) => void` |  |  |
| `options` | `{ value: T; label: ReactNode; color?: string \| undefined; icon?: ReactNode; }[]` |  |  |
| `value` | `string` |  |  |
| `className`? | `string` |  |  |
| `gap`? | `number` | `6` |  |
| `style`? | `CSSProperties` |  |  |

## States

- Default

Source: `frontend/src/components/ui/FilterPills.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
