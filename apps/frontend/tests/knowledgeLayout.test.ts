import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const viewSource = readFileSync(
  fileURLToPath(new URL("../src/views/KnowledgeView.vue", import.meta.url)),
  "utf-8"
);
const listSource = readFileSync(
  fileURLToPath(new URL("../src/components/KnowledgeDocumentList.vue", import.meta.url)),
  "utf-8"
);
const detailSource = readFileSync(
  fileURLToPath(new URL("../src/components/KnowledgeDocumentDetail.vue", import.meta.url)),
  "utf-8"
);

describe("knowledge document scrolling layout", () => {
  it("gives the desktop document list a bounded scrollable region", () => {
    expect(viewSource).toMatch(
      /\.knowledge-view\s*\{[^}]*display:\s*flex;[^}]*height:\s*100%;[^}]*overflow:\s*hidden;/s
    );
    expect(viewSource).toMatch(
      /\.knowledge-view__body\s*\{[^}]*flex:\s*1 1 auto;[^}]*min-height:\s*0;[^}]*overflow:\s*hidden;/s
    );
    expect(viewSource).toMatch(
      /\.knowledge-view__documents\s*\{[^}]*grid-template-rows:\s*auto minmax\(0, 1fr\);[^}]*overflow:\s*hidden;/s
    );
    expect(listSource).toMatch(
      /\.knowledge-document-list\s*\{[^}]*overflow:\s*auto;[^}]*scrollbar-gutter:\s*stable;/s
    );
  });

  it("bounds expanded detail and preview while restoring natural mobile flow", () => {
    expect(detailSource).toMatch(
      /\.knowledge-document-detail\s*\{[^}]*max-height:\s*clamp\([^}]*overflow-y:\s*auto;/s
    );
    expect(detailSource).toMatch(
      /\.knowledge-document-detail__preview ol\s*\{[^}]*max-height:\s*clamp\([^}]*overflow-y:\s*auto;/s
    );
    expect(detailSource).toMatch(
      /@media \(max-width:\s*760px\)[^{]*\{[^}]*\.knowledge-document-detail[^}]*max-height:\s*none;[^}]*overflow:\s*visible;/s
    );
  });
});
