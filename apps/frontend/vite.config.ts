import { fileURLToPath, URL } from "node:url";

import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vitest/config";
import { publicConfigPlugin } from "./build/publicConfig";

export default defineConfig(({ mode }) => ({
  plugins: [vue(), publicConfigPlugin(fileURLToPath(new URL("../..", import.meta.url)), mode)],
  ...(mode === "e2e" ? {
    server: {
      proxy: {
        "/api": {
          target: "http://127.0.0.1:18080",
          rewrite: (path: string) => path.replace(/^\/api/, ""),
        },
      },
    },
  } : {}),
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@agent-py/api-contracts": fileURLToPath(
        new URL("../../packages/api-contracts/src/index.ts", import.meta.url)
      )
    }
  },
  test: {
    include: ["tests/**/*.test.ts"]
  }
}));
