import { expect, test, type Page } from "@playwright/test";

async function register(page: Page): Promise<void> {
  await page.goto("/register");
  await page.getByLabel("昵称").fill("Browser tester");
  await page.getByLabel("邮箱").fill(`browser-${crypto.randomUUID()}@example.com`);
  await page.getByLabel("密码", { exact: true }).fill("browser-test-only-password");
  await page.getByRole("button", { name: "注册并进入" }).click();
  await expect(page).toHaveURL(/\/chat$/);
}

test("registration persists authentication, enforces ownership, and revokes logout", async ({ page, request }) => {
  await page.goto("/knowledge");
  await expect(page).toHaveURL(/\/login/);
  await register(page);
  const token = await page.evaluate(() => localStorage.getItem("super-ai.auth-token"));
  expect(token).not.toBeNull();
  const headers = { Authorization: `Bearer ${token}` };
  const sessionResponse = await request.post("/api/chat/sessions", { headers, data: { title: "Owner only" } });
  const session = await sessionResponse.json() as { data: { id: string } };
  const otherResponse = await request.post("/api/auth/register", { data: {
    email: `other-${crypto.randomUUID()}@example.com`, displayName: "Other",
    password: "browser-test-only-password",
  } });
  const other = await otherResponse.json() as { data: { accessToken: string } };
  const forbidden = await request.get(`/api/chat/sessions/${session.data.id}`, {
    headers: { Authorization: `Bearer ${other.data.accessToken}` },
  });
  expect(forbidden.status()).toBe(403);
  await page.reload();
  await expect(page.getByRole("button", { name: "退出登录" })).toBeVisible();
  await page.getByRole("button", { name: "退出登录" }).click();
  await expect(page).toHaveURL(/\/login$/);
  const revoked = await request.get("/api/auth/me", { headers });
  expect(revoked.status()).toBe(401);
});

test("document upload indexes, reloads, previews and deletes through the API", async ({ page }) => {
  await register(page);
  await page.getByRole("link", { name: "知识库", exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "browser-runbook.md", mimeType: "text/markdown",
    buffer: Buffer.from("# Browser test runbook\n\nCheck connection pool saturation and API timeout."),
  });
  await expect(page.getByText("browser-runbook.md", { exact: true })).toBeVisible();
  await expect(page.getByText("已完成", { exact: true }).first()).toBeVisible();
  await page.reload();
  await expect(page.getByText("browser-runbook.md", { exact: true })).toBeVisible();
  await page.getByText("展开文档详情与分片预览").click();
  await expect(page.getByText("Check connection pool saturation and API timeout.", { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: "删除文档" }).click();
  await page.getByRole("alertdialog", { name: "确认删除文档" }).getByRole("button", { name: "确认删除", exact: true }).click();
  await expect(page.getByText("browser-runbook.md", { exact: true })).toHaveCount(0);
});

test("diagnostic continues after browser disconnect and persisted report can be reopened", async ({ page, request }) => {
  await register(page);
  await page.getByRole("link", { name: "智能诊断", exact: true }).click();
  const query = `Browser disconnect ${crypto.randomUUID()}`;
  await page.getByLabel("诊断问题", { exact: true }).fill(query);
  const createdResponse = page.waitForResponse(response => response.url().endsWith("/aiops/diagnostics") && response.request().method() === "POST");
  await page.getByRole("button", { name: "开始诊断" }).click();
  const created = await (await createdResponse).json() as { data: { id: string } };
  const token = await page.evaluate(() => localStorage.getItem("super-ai.auth-token"));
  await page.reload();
  await expect.poll(async () => {
    const response = await request.get(`/api/aiops/diagnostics/${created.data.id}`, {
      headers: { Authorization: `Bearer ${token}` },
    });
    const result = await response.json() as { data: { status: string } };
    return result.data.status;
  }).toBe("succeeded");
  await page.getByRole("button").filter({ hasText: query }).click();
  await expect(page.getByText("Persisted report survives browser disconnection.")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  const widthFits = await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth);
  expect(widthFits).toBe(true);
});
