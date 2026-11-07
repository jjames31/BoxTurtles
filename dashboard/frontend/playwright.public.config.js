import { defineConfig } from "@playwright/test";
import { existsSync, mkdirSync, mkdtempSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
const root = fileURLToPath(new URL("..", import.meta.url));
const localPython = path.join(root, ".venv/bin/python");
const python = existsSync(localPython) ? localPython : "python3";
const testRoot = path.join(root, ".tools/public-e2e");
mkdirSync(testRoot, { recursive: true });
const data = mkdtempSync(path.join(testRoot, "run-"));
export default defineConfig({
  testDir: "./public-tests",
  workers: 1,
  timeout: 45000,
  reporter: "list",
  use: {
    baseURL: "http://127.0.0.1:8024",
    browserName: "chromium",
    viewport: { width: 1440, height: 1000 },
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  webServer: {
    command: `"${python}" -m uvicorn backend.app.public:create_app --factory --host 127.0.0.1 --port 8024 --no-proxy-headers`,
    cwd: root,
    url: "http://127.0.0.1:8024/api/health",
    timeout: 90000,
    reuseExistingServer: false,
    env: {
      TURTLE_DATA_DIR: data,
      TURTLE_REQUESTS_PER_MINUTE: "10000",
      TURTLE_ADMIN_TOKEN: "public-browser-test-token",
    },
  },
});
