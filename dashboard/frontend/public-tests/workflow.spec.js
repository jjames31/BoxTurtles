import { test, expect } from "@playwright/test";
const blank = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a9t0AAAAASUVORK5CYII=",
  "base64",
);
test("upload real-model negative image, restore results, browse gallery and map", async ({
  page,
}) => {
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "A closer look at the wild." }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Upload media", exact: true }).click();
  await page
    .locator("input[type=file]")
    .setInputFiles({ name: "blank.png", mimeType: "image/png", buffer: blank });
  await page.getByRole("button", { name: "Find turtles", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "No turtles detected", exact: true }),
  ).toBeVisible({ timeout: 30000 });
  await expect(
    page.getByRole("img", { name: "Original frame", exact: true }),
  ).toBeVisible();
  await page.reload();
  await expect(
    page.getByRole("heading", { name: "No turtles detected", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Detections", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Your discoveries, collected." }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Detection map", exact: true }).click();
  await expect(
    page.getByText(
      "No detections with GPS in this view. Locations are never estimated.",
    ),
  ).toBeVisible();
  expect(errors).toEqual([]);
});
test("mobile navigation and layout fit the viewport", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Toggle navigation" }).click();
  await page.getByRole("link", { name: "Upload media", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Every discovery starts here." }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
});

test("administrator unlock, cancel and confirmed reject/delete against the real backend", async ({
  page,
  request,
}) => {
  const imagePath = process.env.TURTLE_TEST_IMAGE;
  test.skip(
    !imagePath,
    "Set TURTLE_TEST_IMAGE to a real turtle photograph for this workflow.",
  );
  const { readFile } = await import("node:fs/promises");
  const upload = await request.post("/api/upload", {
    multipart: {
      file: {
        name: "admin-browser-test.jpg",
        mimeType: "image/jpeg",
        buffer: await readFile(imagePath),
      },
    },
  });
  expect(upload.status()).toBe(202);
  const jobId = (await upload.json()).data.id;
  let result;
  await expect
    .poll(
      async () => {
        result = (await (await request.get(`/api/jobs/${jobId}`)).json()).data;
        return result.status;
      },
      { timeout: 30000 },
    )
    .toBe("completed");
  expect(result.detections_created).toBeGreaterThan(0);
  const image = result.images[0];
  const detection = image.detections[0];
  await page.goto("/#detections");
  await page
    .getByRole("button", { name: /turtle with detection bounding box/ })
    .first()
    .click();
  await page.getByText("Administrator review", { exact: true }).click();
  await page.getByLabel("Administrator token").fill("wrong-token");
  await page
    .getByRole("button", { name: "Unlock admin actions", exact: true })
    .click();
  await expect(page.getByRole("status")).toContainText(
    "Invalid administrator token",
  );
  await page
    .getByLabel("Administrator token")
    .fill("  Bearer public-browser-test-token  ");
  await page
    .getByRole("button", { name: "Unlock admin actions", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Reject & delete image", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Reject & delete image", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Cancel deletion", exact: true })
    .click();
  expect((await request.get(image.original_url)).status()).toBe(200);
  expect(
    (await (await request.get("/api/detections")).json()).data.find(
      (item) => item.id === detection.id,
    ).status,
  ).toBe("pending");
  await page
    .getByRole("button", { name: "Reject & delete image", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Confirm reject and delete", exact: true })
    .click();
  await expect(page.getByRole("dialog")).not.toBeVisible();
  expect((await request.get(image.original_url)).status()).toBe(404);
  expect((await request.get(image.annotated_url)).status()).toBe(404);
  expect(
    (await (await request.get("/api/detections")).json()).data.find(
      (item) => item.id === detection.id,
    ),
  ).toBeUndefined();
});
