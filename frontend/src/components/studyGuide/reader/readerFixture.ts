/**
 * The contract fixture, for tests. It is the same file the backend validates
 * against its models (`backend/tests/fixtures/study_guide_contract.json`), so
 * a reader that renders it is a reader that renders what the server sends.
 */
import fs from "node:fs";
import path from "node:path";

import type { GuideDetail } from "@/lib/studyGuide/types";

const FIXTURE_PATH = path.resolve(__dirname, "../../../../../backend/tests/fixtures/study_guide_contract.json");

/** A fresh copy of the fixture, with any fields replaced. */
export function fixtureGuide(over: Partial<GuideDetail> = {}): GuideDetail {
  return { ...(JSON.parse(fs.readFileSync(FIXTURE_PATH, "utf8")) as GuideDetail), ...over };
}
