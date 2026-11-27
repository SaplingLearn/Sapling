"use client";
/**
 * Menu — a button that opens a short list of actions or choices
 * (`role="menu"`), on Radix's DropdownMenu.
 *
 * Radix does the behaviour every hand-built menu here re-did slightly
 * differently: focus moves into the menu on open and back to the button on
 * close, Up/Down/Home/End and type-ahead move between items, Escape and a
 * press outside close it, and the panel flips to stay on screen. Tab does
 * nothing inside an open menu (Radix's rule): Escape is the way out. This file
 * only adds Sapling's look, which was already the same in each copy: a
 * panel-coloured card with a hairline border and the large shadow, and
 * 44px-tall rows.
 *
 *   <Menu>
 *     <MenuTrigger asChild><button aria-label="More">…</button></MenuTrigger>
 *     <MenuContent label="Guide actions" align="end">
 *       <MenuItem onSelect={save}>Save</MenuItem>
 *       <MenuSeparator />
 *       <MenuItem disabled={busy} onSelect={regenerate}>Regenerate</MenuItem>
 *     </MenuContent>
 *   </Menu>
 */
import React from "react";
import * as DropdownMenu from "@radix-ui/react-dropdown-menu";
import { cn } from "@/lib/cn";

/** Not modal: the rest of the page stays readable and clickable while a menu
 *  is open, and a press outside just closes it. */
export function Menu({ modal = false, ...rest }: React.ComponentPropsWithoutRef<typeof DropdownMenu.Root>) {
  return <DropdownMenu.Root modal={modal} {...rest} />;
}
export const MenuTrigger = DropdownMenu.Trigger;
export const MenuGroup = DropdownMenu.Group;
export const MenuRadioGroup = DropdownMenu.RadioGroup;

export interface MenuContentProps extends React.ComponentPropsWithoutRef<typeof DropdownMenu.Content> {
  /** The menu's accessible name. */
  label: string;
  /** Panel width as a Tailwind class. */
  width?: string;
}

export const MenuContent = React.forwardRef<HTMLDivElement, MenuContentProps>(function MenuContent(
  { label, width = "w-52.5", className, sideOffset = 6, align = "start", loop = true, children, ...rest },
  ref,
) {
  return (
    <DropdownMenu.Portal>
      <DropdownMenu.Content
        ref={ref}
        aria-label={label}
        sideOffset={sideOffset}
        align={align}
        loop={loop}
        // Open on the first item however the menu was opened (Radix focuses
        // the panel on a mouse open), as Sapling's menus always have.
        // DropdownMenu's types omit this prop; its Menu underneath takes it.
        {...({
          onOpenAutoFocus: (event: Event) => {
            event.preventDefault();
            const panel = event.currentTarget as HTMLElement | null;
            panel?.querySelector<HTMLElement>('[role^="menuitem"]:not([data-disabled])')?.focus();
          },
        } as object)}
        className={cn(
          "fade-in z-300 p-1.5 flex flex-col gap-0.5 rounded-md bg-bg-panel border border-border shadow-lg outline-none",
          width,
          className,
        )}
        {...rest}
      >
        {children}
      </DropdownMenu.Content>
    </DropdownMenu.Portal>
  );
});

const ITEM =
  "flex items-center gap-3 w-full min-h-11 px-3 rounded-sm text-base font-medium text-text text-left no-underline cursor-pointer select-none outline-none " +
  "data-[highlighted]:bg-bg-subtle data-[disabled]:opacity-50 data-[disabled]:cursor-not-allowed [&_svg]:text-text-dim";

export const MenuItem = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof DropdownMenu.Item>
>(function MenuItem({ className, ...rest }, ref) {
  return <DropdownMenu.Item ref={ref} className={cn(ITEM, className)} {...rest} />;
});

/** A choice in a MenuRadioGroup; the chosen one is bold with a check. */
export const MenuRadioItem = React.forwardRef<
  HTMLDivElement,
  React.ComponentPropsWithoutRef<typeof DropdownMenu.RadioItem> & { check?: React.ReactNode }
>(function MenuRadioItem({ className, children, check, ...rest }, ref) {
  return (
    <DropdownMenu.RadioItem
      ref={ref}
      className={cn(ITEM, "justify-between whitespace-nowrap data-[state=checked]:font-bold", className)}
      {...rest}
    >
      {children}
      <DropdownMenu.ItemIndicator>{check}</DropdownMenu.ItemIndicator>
    </DropdownMenu.RadioItem>
  );
});

export function MenuSeparator({ className }: { className?: string }) {
  return <DropdownMenu.Separator className={cn("h-px my-1 mx-1.5 bg-border", className)} />;
}
