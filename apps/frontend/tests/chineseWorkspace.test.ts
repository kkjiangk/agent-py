// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import AsyncStatusBadge from "../src/components/AsyncStatusBadge.vue";
import { describeAsyncStatus } from "../src/ui/asyncStatus";

describe("中文 AI 工作台状态", () => {
  it("将既有异步状态翻译为用户可理解的中文生命周期", () => {
    expect(describeAsyncStatus("pending")).toMatchObject({ label: "等待中", tone: "waiting", active: true });
    expect(describeAsyncStatus("accepted")).toMatchObject({ label: "准备中", tone: "waiting", active: true });
    expect(describeAsyncStatus("running")).toMatchObject({ label: "执行中", tone: "running", active: true });
    expect(describeAsyncStatus("succeeded")).toMatchObject({ label: "已完成", tone: "success", active: false });
    expect(describeAsyncStatus("indexed")).toMatchObject({ label: "已索引", tone: "success", active: false });
    expect(describeAsyncStatus("failed")).toMatchObject({ label: "执行失败", tone: "danger", active: false });
  });

  it("以可访问文本而不是颜色单独表达活动状态", () => {
    const wrapper = mount(AsyncStatusBadge, {
      props: { status: "running", detail: "正在写入知识库" }
    });

    expect(wrapper.get('[role="status"]').text()).toContain("执行中");
    expect(wrapper.text()).toContain("正在写入知识库");
    expect(wrapper.attributes("data-tone")).toBe("running");
  });
});
