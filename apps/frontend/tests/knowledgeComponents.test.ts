// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { DocumentChunkPreview, DocumentIndexTask, KnowledgeDocument } from "@agent-py/api-contracts";

import KnowledgeDocumentList from "../src/components/KnowledgeDocumentList.vue";
import KnowledgeUpload from "../src/components/KnowledgeUpload.vue";

const document: KnowledgeDocument = {
  id: "doc_1",
  knowledgeBaseId: "kb_1",
  ownerUserId: "user_1",
  filename: "restart.md",
  sizeBytes: 42,
  mimeType: "text/markdown",
  contentHash: "sha256:abc",
  status: "ready",
  indexStatus: "failed",
  uploadedAt: "2026-07-10T00:00:00.000Z",
  updatedAt: "2026-07-10T00:00:00.000Z",
  source: "upload"
};

const task: DocumentIndexTask = {
  id: "task_1",
  ownerUserId: "user_1",
  knowledgeBaseId: "kb_1",
  documentId: "doc_1",
  status: "failed",
  failureReason: "Embedding unavailable",
  retryOfTaskId: null,
  createdAt: "2026-07-10T00:00:00.000Z",
  updatedAt: "2026-07-10T00:00:00.000Z",
  startedAt: "2026-07-10T00:00:00.000Z",
  completedAt: "2026-07-10T00:00:01.000Z"
};

const preview: DocumentChunkPreview = {
  configuration: { strategy: "markdown-heading" },
  totalChunks: 2,
  truncated: false,
  items: [
    { index: 0, characterCount: 42, excerpt: "# Restart\nRestart the API." },
    { index: 1, characterCount: 37, excerpt: "## Verify\nCheck readiness." }
  ]
};

describe("knowledge components", () => {
  it("rejects a file outside the shared upload policy before emitting an upload", async () => {
    const wrapper = mount(KnowledgeUpload, { props: { disabled: false } });
    const input = wrapper.get('input[type="file"]');
    const file = new File(["binary"], "unsafe.exe", { type: "application/octet-stream" });

    Object.defineProperty(input.element, "files", { configurable: true, value: [file] });
    await input.trigger("change");

    expect(wrapper.text()).toContain("仅支持 Markdown(.md) 与 PDF(.pdf)");
    expect(wrapper.emitted("upload")).toBeUndefined();
  });

  it("only shows fixed-character numeric controls and emits compact non-fixed chunking", async () => {
    const wrapper = mount(KnowledgeUpload, { props: { disabled: false } });

    expect(wrapper.text()).toContain("最大字符");
    await wrapper.get("select").setValue("paragraph");
    expect(wrapper.text()).not.toContain("最大字符");
    expect(wrapper.text()).toContain("无需设置字符数和重叠参数");
    expect(wrapper.findAll('input[type="number"]')).toHaveLength(0);

    const input = wrapper.get('input[type="file"]');
    const file = new File(["# Runbook"], "runbook.md", { type: "text/markdown" });
    Object.defineProperty(input.element, "files", { configurable: true, value: [file] });
    await input.trigger("change");

    expect(wrapper.emitted("upload")?.[0]).toEqual([file, { strategy: "paragraph" }]);
  });

  it("shows index failure context and emits retry, inline detail, and delete actions", async () => {
    const wrapper = mount(KnowledgeDocumentList, {
      props: { documents: [document], indexTasks: [task] }
    });

    expect(wrapper.text()).toContain("执行失败");
    expect(wrapper.text()).toContain("Embedding unavailable");
    await wrapper.get('button[title="重试索引"]') .trigger("click");
    const detail = wrapper.get("details");
    (detail.element as HTMLDetailsElement).open = true;
    await detail.trigger("toggle");
    await wrapper.get('button[title="删除文档"]') .trigger("click");

    expect(wrapper.emitted("retry")).toEqual([[task]]);
    expect(wrapper.emitted("detail")).toEqual([[document]]);
    expect(wrapper.emitted("delete")).toEqual([[document]]);
  });

  it("keeps each document detail collapsed inline until the user expands it", () => {
    const wrapper = mount(KnowledgeDocumentList, {
      props: { documents: [document], indexTasks: [task] }
    });

    expect(wrapper.get("summary").text()).toContain("展开文档详情与分片预览");
    expect(wrapper.get("details").attributes("open")).toBeUndefined();
  });

  it("renders metadata and chunk previews inside the matching document disclosure", () => {
    const wrapper = mount(KnowledgeDocumentList, {
      props: {
        documents: [document],
        indexTasks: [task],
        preview,
        selectedDocument: document
      }
    });

    expect(wrapper.text()).toContain("文件大小");
    expect(wrapper.text()).toContain("共 2 个分片");
    expect(wrapper.text()).toContain("Restart the API.");
  });
});
