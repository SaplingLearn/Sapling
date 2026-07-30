/**
 * Public-rooms journey (#405, "real ownership + public rooms").
 *
 * As the seeded student: create a room through the UI with a topic and the
 * Public flag. Assert the DB semantics the 0038 migration + populate-on-create
 * established: owner_id = creator (real, transferable ownership — created_by
 * stays the immutable creator record), is_public true, topic stored. Then, as
 * the SECOND seeded user in a separate browser context, discover the room in
 * the "Public rooms" list and join it WITHOUT an invite code — the whole point
 * of is_public — and assert the membership row. The public listing payload
 * never carries invite_code (pinned by backend tests; the UI never sees it).
 */
import { expect, test } from "./support/fixtures";
import { queryRaw } from "./support/db";
import { mintStorageState } from "./support/session";
import { FRONTEND_URL, USER_ACTIVE, USER_SECOND } from "./support/stack";

const ROOM_NAME = "E2E Public Room";

test("a public room is created with real semantics and joined invite-less (#405)", async ({
  page,
  browser,
}) => {
  await page.goto(`${FRONTEND_URL}/social`);
  await page.getByTestId("social-create-room").click();
  await page.getByTestId("social-create-join-input").fill(ROOM_NAME);
  await page.getByTestId("social-create-topic").fill("Midterm prep");
  await page.getByTestId("social-create-public").check();
  await page.getByTestId("social-create-join-submit").click();

  // DB semantics (never a bare sleep): owner seeded to the creator, flag real.
  await expect
    .poll(
      async () => {
        const rows = await queryRaw(
          "SELECT id, owner_id, created_by, topic, is_public FROM rooms WHERE name = $1",
          [ROOM_NAME],
        );
        return rows.length;
      },
      { timeout: 5_000, message: "the room row should land with the #405 columns" },
    )
    .toBe(1);
  const [room] = await queryRaw(
    "SELECT id, owner_id, created_by, topic, is_public FROM rooms WHERE name = $1",
    [ROOM_NAME],
  );
  expect(room.owner_id).toBe(USER_ACTIVE);
  expect(room.created_by).toBe(USER_ACTIVE);
  expect(room.topic).toBe("Midterm prep");
  expect(room.is_public).toBe(true);

  // Second user discovers and joins WITHOUT an invite.
  const ctx2 = await browser.newContext({
    storageState: await mintStorageState(USER_SECOND, "Casey Second"),
  });
  try {
    const page2 = await ctx2.newPage();
    await page2.goto(`${FRONTEND_URL}/social`);
    await page2.getByTestId(`social-public-join-${room.id}`).click();
    await expect(page2.getByTestId(`social-room-item-${room.id}`)).toBeVisible();

    const members = await queryRaw(
      "SELECT user_id FROM room_members WHERE room_id = $1 AND user_id = $2",
      [room.id, USER_SECOND],
    );
    expect(members).toHaveLength(1);
  } finally {
    await ctx2.close();
  }
});
