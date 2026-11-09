import { fetchJSON } from "@/lib/api";

export type FlagMap = Record<string, string>;

/** The signed-in student's client-visible flags (#620). Throws when the
 * backend could not read its flag store (`degraded`, #771): that answer is
 * every flag's fail-closed "off", which would UN-hide hidden features, so the
 * caller treats it like a failed read and keeps its last-known map. */
export async function fetchFlags(): Promise<FlagMap> {
  const res = await fetchJSON<{ flags?: FlagMap; degraded?: boolean }>("/api/flags");
  if (res.degraded) throw new Error("flag store unreadable");
  return res.flags ?? {};
}
