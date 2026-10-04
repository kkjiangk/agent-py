// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import type { ChatAssemblyConfigurationResponse } from "@agent-py/api-contracts";

import ChatPromptSidebar from "../src/components/ChatPromptSidebar.vue";
import ChatSkillSidebar from "../src/components/ChatSkillSidebar.vue";

describe("chat configuration sidebars", () => {
  it("manages collapsible system prompts as a single-select sidebar", async () => {
    const wrapper = mount(ChatPromptSidebar, {
      props: { configuration: configuration(), isSaving: false }
    });

    expect(wrapper.text()).toContain("对话系统提示词设置");
    expect(wrapper.text()).toContain("使用中");
    await wrapper.get('textarea').setValue("更新后的 PROMPT_MARKER");
    await wrapper.findAll("button").find((item) => item.text().includes("保存"))?.trigger("click");
    expect(wrapper.emitted("updatePrompt")?.[0]).toEqual([
      "prompt_1",
      "默认提示词",
      "更新后的 PROMPT_MARKER"
    ]);

    await wrapper.get('button[title="新建提示词"]').trigger("click");
    const inputs = wrapper.findAll("input");
    await inputs[0]?.setValue("新提示词");
    await wrapper.findAll("textarea")[0]?.setValue("新的系统提示词");
    await wrapper.findAll("button").find((item) => item.text().includes("创建"))?.trigger("click");
    expect(wrapper.emitted("createPrompt")?.[0]).toEqual(["新提示词", "新的系统提示词"]);

    await wrapper.get('button[title="使用提示词"]').trigger("click");
    expect(wrapper.emitted("save")?.[0]).toEqual(["prompt_1", []]);

    await wrapper.findAll("button").find((item) => item.text().includes("删除"))?.trigger("click");
    expect(wrapper.emitted("deletePrompt")?.[0]).toEqual(["prompt_1"]);
  });

  it("uploads, selects, saves, and deletes skills as a multi-select sidebar", async () => {
    const wrapper = mount(ChatSkillSidebar, {
      props: { configuration: configuration(), isSaving: false }
    });
    const file = new File(
      ["---\nname: ops\ndescription: 运维分析\n---\n# Skill\nSKILL_MARKER"],
      "SKILL.md",
      { type: "text/markdown" }
    );
    const input = wrapper.get('input[type="file"]');

    expect(wrapper.text()).toContain("Skill 设置");
    expect(wrapper.text()).toContain("Skill 上传规范");
    expect(wrapper.text()).toContain("ops-analysis");
    expect(wrapper.text()).toContain("分析日志、告警和运行状态");
    Object.defineProperty(input.element, "files", { value: [file], configurable: true });
    await input.trigger("change");
    await Promise.resolve();
    expect(wrapper.emitted("uploadSkill")?.[0]).toEqual([file]);

    await wrapper.get('input[type="checkbox"]').setValue(true);
    await wrapper.findAll("button").find((item) => item.text().includes("保存使用的 Skill"))?.trigger("click");
    expect(wrapper.emitted("save")?.[0]).toEqual(["prompt_1", ["skill_1"]]);

    await wrapper.get('button[title="删除 Skill"]').trigger("click");
    expect(wrapper.emitted("deleteSkill")?.[0]).toEqual(["skill_1"]);
  });

  it("keeps a collapsed prompt closed after Skill configuration refreshes", async () => {
    const wrapper = mount(ChatPromptSidebar, {
      props: { configuration: configuration(), isSaving: false }
    });
    const summary = wrapper.get(".chat-prompt-sidebar__summary");

    expect(summary.attributes("aria-expanded")).toBe("true");
    await summary.trigger("click");
    expect(summary.attributes("aria-expanded")).toBe("false");

    const refreshed = configuration();
    await wrapper.setProps({
      configuration: {
        ...refreshed,
        selection: { ...refreshed.selection, skillIds: ["skill_1"], updatedAt: "2026-07-11T00:01:00Z" }
      }
    });

    expect(summary.attributes("aria-expanded")).toBe("false");
    expect(wrapper.find(".chat-prompt-sidebar__editor").exists()).toBe(false);
  });

  it("explains invalid skill uploads before sending them to the backend", async () => {
    const wrapper = mount(ChatSkillSidebar, {
      props: { configuration: configuration(), isSaving: false }
    });
    const input = wrapper.get('input[type="file"]');
    const file = new File(["# Skill"], "Ops.md", { type: "text/markdown" });

    Object.defineProperty(input.element, "files", { value: [file], configurable: true });
    await input.trigger("change");

    expect(wrapper.text()).toContain("必须严格为 SKILL.md");
    expect(wrapper.emitted("uploadSkill")).toBeUndefined();
  });
});

function configuration(): ChatAssemblyConfigurationResponse {
  return {
    prompts: [
      {
        id: "prompt_1",
        label: "默认提示词",
        content: "原始提示词",
        isDefault: true,
        createdAt: "2026-07-11T00:00:00Z",
        updatedAt: "2026-07-11T00:00:00Z"
      }
    ],
    skills: [
      {
        id: "skill_1",
        filename: "SKILL.md",
        name: "ops-analysis",
        description: "分析日志、告警和运行状态",
        label: "ops-analysis",
        contentPreview: "分析日志、告警和运行状态",
        sizeBytes: 22,
        createdAt: "2026-07-11T00:00:00Z",
        updatedAt: "2026-07-11T00:00:00Z"
      }
    ],
    selection: {
      systemPromptId: "prompt_1",
      skillIds: [],
      updatedAt: "2026-07-11T00:00:00Z"
    }
  };
}
