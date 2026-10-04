import { copyFile, mkdir } from "node:fs/promises";
import { resolve } from "node:path";
import { defineConfig } from "vitepress";

export default defineConfig({
  lang: "en-US",
  title: "Agent Py",
  description: "Architecture, operation, and verification of the Agent Py AIOps workspace",
  cleanUrls: true,
  async buildEnd({ srcDir, outDir }) {
    const benchmarkDir = resolve(outDir, "benchmarks");
    await mkdir(benchmarkDir, { recursive: true });
    await copyFile(
      resolve(srcDir, "benchmarks/lexical-benchmark.json"),
      resolve(benchmarkDir, "lexical-benchmark.json"),
    );
  },
  themeConfig: {
    nav: [
      { text: "Guide", link: "/getting-started" },
      { text: "Architecture", link: "/architecture" },
      { text: "Testing", link: "/testing" },
      { text: "Benchmarks", link: "/benchmarks/README" },
    ],
    sidebar: [
      { text: "Project", items: [
        { text: "Getting started", link: "/getting-started" },
        { text: "Architecture", link: "/architecture" },
        { text: "Configuration", link: "/configuration" },
        { text: "Operations", link: "/operations-and-monitoring" },
      ] },
      { text: "Engineering", items: [
        { text: "Decisions", link: "/engineering-quality" },
        { text: "Testing", link: "/testing" },
        { text: "Lexical benchmarks", link: "/benchmarks/README" },
        { text: "Deployment", link: "/deployment" },
        { text: "Evaluation", link: "/evaluation" },
      ] },
      { text: "Integration examples", items: [
        { text: "Real logs and alerts", link: "/tutorials/real-log-and-alert" },
        { text: "Java incident fixture", link: "/aiops/ecommerce-aiops-fixture" },
        { text: "Pricing latency runbook", link: "/aiops/ecommerce-quant-pricing-latency-sop" },
        { text: "Chat skill examples", link: "/examples/skills/README" },
      ] },
    ],
    search: { provider: "local" },
    outline: { level: [2, 3] },
  },
});
