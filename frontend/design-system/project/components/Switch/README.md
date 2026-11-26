# Switch

An on/off setting that applies right away. `label` is the accessible name: name the setting, not the state.

```tsx
import { Switch } from "@/components/ui";
```

## Props

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `checked` | `boolean` |  |  |
| `label` | `string` |  | Accessible name — the setting the switch controls. |
| `onChange` | `(next: boolean) => void` |  |  |
| `disabled`? | `boolean` |  |  |
| `testid`? | `string` |  |  |

## States

- Off
- On
- Disabled
- Disabled On

Source: `frontend/src/components/ui/Switch.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
