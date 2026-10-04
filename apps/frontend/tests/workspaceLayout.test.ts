import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const workspaceSource = readFileSync(
  fileURLToPath(new URL("../src/layouts/WorkspaceLayout.vue", import.meta.url)),
  "utf8"
);
const chatSource = readFileSync(
  fileURLToPath(new URL("../src/views/ChatView.vue", import.meta.url)),
  "utf8"
);
const knowledgeSource = readFileSync(
  fileURLToPath(new URL("../src/views/KnowledgeView.vue", import.meta.url)),
  "utf8"
);

describe("edge-to-edge desktop workspace", () => {
  it("removes the centered max-width and outer padding from routed content", () => {
    expect(workspaceSource).toMatch(
      /\.workspace-layout__main\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\);[^}]*height:\s*100dvh;/s
    );
    expect(workspaceSource).toMatch(
      /\.workspace-layout__content\s*\{ height:\s*100%; min-height:\s*0; overflow:\s*hidden; width:\s*100%; \}/
    );
    expect(workspaceSource).not.toMatch(/\.workspace-layout__content\s*\{[^}]*max-width:/s);
  });

  it("lets chat and knowledge own the full routed surface", () => {
    expect(chatSource).toMatch(/\.chat-view\s*\{[^}]*height:\s*100%;[^}]*overflow:\s*hidden;/s);
    expect(chatSource).not.toMatch(/\.chat-view\s*\{[^}]*border-radius:/s);
    expect(knowledgeSource).toMatch(
      /\.knowledge-view\s*\{[^}]*height:\s*100%;[^}]*overflow:\s*hidden;/s
    );
  });
});
