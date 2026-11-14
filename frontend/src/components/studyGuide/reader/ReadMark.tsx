import { Icon } from "@/components/Icon";

import s from "./reader.module.css";

/** The round tick of a read toggle: filled once the section is read. */
export function ReadMark({ read }: { read: boolean }) {
  return (
    <span className={read ? `${s.readMark} ${s.readMarkOn}` : s.readMark} aria-hidden="true">
      <Icon name="check" size={11} />
    </span>
  );
}
