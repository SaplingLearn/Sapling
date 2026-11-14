import s from "./pieces.module.css";
import { ReadOut } from "./ReadOut";

/**
 * The class a guide belongs to, by its short code. The full name is the
 * tooltip and is read out after the code. `color` is the class's colour
 * (`classColor`); without one there is no dot.
 */
export function ClassTag({ code, name, color }: { code: string; name: string; color?: string }) {
  return (
    <span className={s.classTag} title={name}>
      {color && <span className={s.classDot} style={{ background: color }} aria-hidden="true" />}
      <span className={s.classCode}>{code}</span>
      {name !== code && <ReadOut>, {name}</ReadOut>}
    </span>
  );
}
