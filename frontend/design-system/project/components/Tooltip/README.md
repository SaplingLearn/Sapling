# Tooltip

A short hint on hover or focus. Never put the only way to do something in a tooltip. `InfoTip` is the small (?) button that holds one.

```tsx
import { Tooltip } from "@/components/ui";
```

## Props

### Tooltip

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `content` | `ReactNode` |  |  |
| `delayMs`? | `number` | `250` |  |
| `placement`? | `"top" \| "bottom"` | `top` |  |

### InfoTip

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `content` | `ReactNode` |  |  |
| `label`? | `string` | `More info` |  |

## States

- Top
- Bottom
- Info

Source: `frontend/src/components/ui/Tooltip.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
