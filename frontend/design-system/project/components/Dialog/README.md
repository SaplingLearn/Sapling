# Dialog

A centred modal for a decision or a short form that blocks the page. Handles focus, Escape, the Tab trap and scroll lock. For a side panel use `Sheet`; for a read-mostly list use `PanelModal`; for a custom overlay build on `useOverlayBehaviour`. Never hand-build a `fixed inset-0` overlay.

```tsx
import Dialog from "@/components/Dialog";
```

## Props

### useOverlayBehaviour

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `onClose` | `() => void` |  |  |
| `open` | `boolean` |  |  |
| `dismissible`? | `boolean` | `true` |  |
| `initialFocusRef`? | `RefObject<HTMLElement \| null>` |  |  |

### Dialog

| Prop | Type | Default | Notes |
| --- | --- | --- | --- |
| `onClose` | `() => void` |  |  |
| `open` | `boolean` |  |  |
| `dismissible`? | `boolean` | `true` |  |
| `initialFocusRef`? | `RefObject<HTMLElement \| null>` |  | Element to focus on open. Without it focus lands on the first focusable node in the panel — the close button, since it precedes {children} in the DOM. Form dialogs pass their first field instead. `autoFocus` can't do this job: React fires it at mount, before the focus pass below. |
| `labelledBy`? | `string` |  |  |
| `padding`? | `string` | `28px` |  |
| `showCloseButton`? | `boolean` | `true` |  |
| `size`? | `"sm" \| "md" \| "lg" \| "xl"` | `md` |  |
| `title`? | `string` |  |  |
| `width`? | `string` |  | Panel width as a CSS length (e.g. `min(980px, calc(100vw - 32px))`), for a dialog wider than the `size` presets. Replaces the preset width only: the panel's max-width still applies, so it never outgrows a small screen. |
| `zIndex`? | `number` | `100` |  |

## States

- Confirm
- Small
- Large
- Not Dismissible

Source: `frontend/src/components/Dialog.tsx`. The preview is a static render of its Storybook stories, styled by `components/bundle.css`; build with the classes it shows.
