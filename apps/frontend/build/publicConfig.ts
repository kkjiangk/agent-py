import { existsSync, readFileSync } from "node:fs";
import { resolve } from "node:path";

import type { Plugin } from "vite";

export function publicApiBaseUrl(base: unknown, override: unknown): string {
  function address(value: unknown): string | undefined {
    if (value === null || typeof value !== "object" || !("frontend" in value)) return undefined;
    const frontend = value.frontend;
    if (frontend === null || typeof frontend !== "object" || !("apiBaseUrl" in frontend)) return undefined;
    return typeof frontend.apiBaseUrl === "string" ? frontend.apiBaseUrl : undefined;
  }
  const selected = address(override) ?? address(base);
  if (selected === undefined || selected.trim().length === 0) {
    throw new Error("frontend.apiBaseUrl must be a nonempty public URL.");
  }
  return selected.trim().replace(/\/+$/, "");
}

export function publicConfigPlugin(repositoryRoot: string, mode: string): Plugin {
  const moduleId = "virtual:agent-py-public-config";
  const resolvedId = `\0${moduleId}`;
  return {
    name: "agent-py-public-config",
    resolveId(id) {
      return id === moduleId ? resolvedId : undefined;
    },
    load(id) {
      if (id !== resolvedId) return undefined;
      function read(relative: string, fallback: string): unknown {
        const path = resolve(repositoryRoot, relative);
        return JSON.parse(readFileSync(existsSync(path) ? path : resolve(repositoryRoot, fallback), "utf8"));
      }
      // Private JSON stays in the Node build process. Only this allowlisted scalar
      // is emitted into the browser module; tests never read developer secrets.
      const apiBaseUrl = mode === "e2e" ? "/api" : publicApiBaseUrl(
        read("config/project.json", "config/project.template.json"),
        read("config/user.project.json", "config/user.project.template.json"),
      );
      return `export const apiBaseUrl = ${JSON.stringify(apiBaseUrl)};`;
    },
  };
}
