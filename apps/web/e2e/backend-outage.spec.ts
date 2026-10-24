// The e2e fixture deliberately has no live API: PRINCESS_API_BASE uses a
// blocked/unavailable port. Every same-origin route must fail closed as JSON,
// without an uncaught Next.js server error or leaked network/credential details.
import { expect, test } from "@playwright/test";

const ORIGIN = "http://127.0.0.1:3100";

test("API proxy exposes bounded 502 when the upstream cannot be reached", async ({ request }) => {
  const response = await request.get("/api/v1/me");
  expect(response.status()).toBe(502);
  expect(response.headers()["content-type"]).toContain("application/json");
  expect(response.headers()["cache-control"]).toBe("no-store");
  expect(await response.json()).toEqual({ error: "upstream_unavailable" });
});

test("guest session transport fails closed when the upstream is unavailable", async ({ request }) => {
  const response = await request.post("/api/session/guest", { headers: { origin: ORIGIN } });
  expect(response.status()).toBe(502);
  expect(await response.json()).toEqual({ error: "guest_unavailable" });
  expect(response.headers()["set-cookie"]).toBeUndefined();
});

test("test-only dev login fails closed and never issues a cookie on upstream failure", async ({ request }) => {
  const response = await request.post("/api/session/dev-login", {
    headers: { origin: ORIGIN },
    data: { subject: "offline-fixture" },
  });
  expect(response.status()).toBe(502);
  expect(await response.json()).toEqual({ error: "login_unavailable" });
  expect(response.headers()["set-cookie"]).toBeUndefined();
});
