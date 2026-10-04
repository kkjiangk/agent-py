import { describe, expect, it } from "vitest";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { build } from "vite";

import { publicApiBaseUrl, publicConfigPlugin } from "../build/publicConfig";

describe("public frontend configuration", () => {
  it("selects only the API URL and retains the user override", () => {
    const base = { frontend: { apiBaseUrl: "http://127.0.0.1:8000/" }, llm: { apiKey: "private-canary" } };
    const override = { frontend: { apiBaseUrl: "https://api.example.com/" }, secretKey: "cloud-canary" };
    const exposed = publicApiBaseUrl(base, override);
    expect(exposed).toBe("https://api.example.com");
    expect(exposed).not.toContain("canary");
  });

  it("supports template-only builds and rejects missing public settings", () => {
    expect(publicApiBaseUrl({ frontend: { apiBaseUrl: "http://127.0.0.1:8000" } }, {})).toBe("http://127.0.0.1:8000");
    expect(() => publicApiBaseUrl({}, { apiKey: "private-canary" })).toThrow();
  });

  it("emits only the allowlisted URL in an actual Vite build", async () => {
    const directory = mkdtempSync(join(tmpdir(), "agent-py-public-config-"));
    try {
      mkdirSync(join(directory, "config"));
      writeFileSync(join(directory, "config/project.template.json"), JSON.stringify({
        frontend: { apiBaseUrl: "https://api.example.com" },
        llm: { apiKey: "private-api-canary" }, clsMcpServer: { secretKey: "private-cloud-canary" },
      }));
      writeFileSync(join(directory, "config/user.project.template.json"), "{}");
      const entry = join(directory, "entry.js");
      writeFileSync(entry, 'import {apiBaseUrl} from "virtual:agent-py-public-config"; console.log(apiBaseUrl);');
      const result = await build({
        configFile: false, root: directory, logLevel: "silent",
        plugins: [publicConfigPlugin(directory, "production")],
        build: { write: false, rollupOptions: { input: entry } },
      });
      const serialized = JSON.stringify(result);
      expect(serialized).toContain("https://api.example.com");
      expect(serialized).not.toContain("private-api-canary");
      expect(serialized).not.toContain("private-cloud-canary");
    } finally {
      rmSync(directory, { recursive: true, force: true });
    }
  });
});
