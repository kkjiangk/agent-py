// @vitest-environment jsdom

import { mount } from "@vue/test-utils";
import { describe, expect, it } from "vitest";

import MarkdownContent from "../src/components/MarkdownContent.vue";

describe("MarkdownContent", () => {
  it("renders supported assistant Markdown", () => {
    const wrapper = mount(MarkdownContent, {
      props: { content: "## Recovery\n\nUse the **runbook** and `restart-api`." }
    });

    expect(wrapper.find("h2").text()).toBe("Recovery");
    expect(wrapper.find("strong").text()).toBe("runbook");
    expect(wrapper.find("code").text()).toBe("restart-api");
  });

  it("removes untrusted raw HTML from assistant Markdown", () => {
    const wrapper = mount(MarkdownContent, {
      props: { content: "Safe text <img src=x onerror=alert(1)>" }
    });

    expect(wrapper.html()).not.toContain("<img");
    expect(wrapper.text()).toContain("Safe text");
  });
});
