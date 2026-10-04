import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const aiopsViewSource = readFileSync(
  fileURLToPath(new URL("../src/views/AiopsView.vue", import.meta.url)),
  "utf8"
);
const reportPanelSource = readFileSync(
  fileURLToPath(new URL("../src/components/AiopsReportPanel.vue", import.meta.url)),
  "utf8"
);

describe("AIOps fixed workspace layout", () => {
  it("constrains the desktop workspace and prevents the console from growing with content", () => {
    expect(aiopsViewSource).toMatch(
      /\.aiops-view\s*\{[^}]*height:\s*100%;[^}]*overflow:\s*hidden;/s
    );
    expect(aiopsViewSource).toMatch(/\.aiops-view__console\s*\{[^}]*overflow:\s*hidden;/s);
    expect(aiopsViewSource).toMatch(
      /\.aiops-view__center\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\) minmax\(8rem, 0\.42fr\);[^}]*overflow:\s*hidden;/s
    );
  });

  it("keeps report metadata fixed and scrolls only the Markdown body", () => {
    expect(reportPanelSource).toMatch(
      /\.aiops-report\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\);[^}]*overflow:\s*hidden;/s
    );
    expect(reportPanelSource).toMatch(
      /\.aiops-report__document\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\) auto;[^}]*overflow:\s*hidden;/s
    );
    expect(reportPanelSource).toMatch(
      /\.aiops-report__document > :deep\(\.markdown-content\)\s*\{[^}]*overflow-y:\s*auto;/s
    );
  });
});
