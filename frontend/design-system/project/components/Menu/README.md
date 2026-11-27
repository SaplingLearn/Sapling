# Menu

A dropdown of actions or one choice (Radix DropdownMenu: arrow keys, typeahead, Escape, focus return). Never hand-build `role="menu"`.

```tsx
import { Menu } from "@/components/ui";
```

## Props

### MenuSeparator

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `className`? | `string` |  |  |

### MenuTrigger

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `asChild`? | `boolean` |  |  |

### MenuGroup

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `asChild`? | `boolean` |  |  |

### MenuRadioGroup

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `asChild`? | `boolean` |  |  |

### MenuContent

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `label` | `string` |  | The menu's accessible name. |
| `asChild`? | `boolean` |  |  |
| `width`? | `string` | `w-52.5` | Panel width as a Tailwind class. |

### MenuItem

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `asChild`? | `boolean` |  |  |

### MenuRadioItem

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `asChild`? | `boolean` |  |  |
| `check`? | `ReactNode` |  |  |

## States

- Actions
- Closed
- Radio Choice

Source: `frontend/src/components/ui/Menu.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
