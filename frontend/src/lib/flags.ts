import { fetchJSON } from "@/lib/api";

export type FlagMap = Record<string, string>;

/** The signed-in student's client-visible flags (#620). */
export async function fetchFlags(): Promise<FlagMap> {
  const res = await fetchJSON<{ flags?: FlagMap }>("/api/flags");
  return res.flags ?? {};
}
