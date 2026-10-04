<script setup lang="ts">
import { Cable, CheckCircle2, Plus, RefreshCw, Save, Server, Trash2, TriangleAlert, Wrench } from "lucide-vue-next";
import { computed, onMounted, reactive, watch } from "vue";

import type { McpConnectionMutationRequest, McpTransport } from "@agent-py/api-contracts";

import AppLoadingState from "../components/AppLoadingState.vue";
import { useMcpStore } from "../stores/mcp";

const mcp = useMcpStore();
const draft = reactive<McpConnectionMutationRequest>({
  name: "",
  transport: "sse",
  url: "",
  enabled: true,
  timeoutSeconds: 15,
  retries: 1
});
const isNew = computed(() => mcp.selected === null);

watch(() => mcp.selected, (connection) => {
  if (connection === null) return;
  Object.assign(draft, {
    name: connection.name,
    transport: connection.transport,
    url: connection.url,
    enabled: connection.enabled,
    timeoutSeconds: connection.timeoutSeconds,
    retries: connection.retries
  });
}, { immediate: true });

onMounted(() => { void mcp.initialize().catch(() => undefined); });

function newConnection(): void {
  mcp.select("");
  Object.assign(draft, {
    name: "",
    transport: "sse" as McpTransport,
    url: "http://127.0.0.1:3000/sse",
    enabled: true,
    timeoutSeconds: 15,
    retries: 1
  });
}

function run(operation: () => Promise<void>): void {
  void operation().catch(() => undefined);
}
</script>

<template>
  <section class="mcp-view" aria-label="MCP 连接管理">
    <header class="mcp-view__header">
      <div><p>Agent 工具来源</p><h2>MCP 连接</h2><span>管理聊天与智能诊断可以使用的真实 MCP Server。</span></div>
      <button type="button" title="新建连接" @click="newConnection"><Plus :size="16" aria-hidden="true" />新建连接</button>
    </header>
    <AppLoadingState v-if="mcp.isLoading" label="正在加载 MCP 连接" />
    <div v-else class="mcp-view__workspace">
      <aside class="mcp-view__list" aria-label="MCP 连接列表">
        <button v-for="connection in mcp.connections" :key="connection.id" type="button" :class="{ 'mcp-view__connection--active': mcp.selectedId === connection.id }" @click="mcp.select(connection.id)">
          <span class="mcp-view__connection-icon"><Server :size="16" aria-hidden="true" /></span>
          <span><strong>{{ connection.name }}</strong><small>{{ connection.transport === 'sse' ? 'SSE' : 'Streamable HTTP' }} · {{ connection.enabled ? '已启用' : '已停用' }}</small></span>
          <CheckCircle2 v-if="connection.lastCheck?.ok" :size="15" class="mcp-view__ok" aria-label="连接正常" />
          <TriangleAlert v-else-if="connection.lastCheck" :size="15" class="mcp-view__bad" aria-label="连接异常" />
        </button>
        <p v-if="mcp.connections.length === 0">还没有 MCP 连接。</p>
      </aside>

      <main class="mcp-view__editor">
        <form @submit.prevent="run(() => isNew ? mcp.create(draft) : mcp.update(draft))">
          <header><div><p>{{ isNew ? '新建连接' : '连接配置' }}</p><h3>{{ draft.name || '未命名 MCP Server' }}</h3></div><label class="mcp-view__toggle"><input v-model="draft.enabled" type="checkbox" /><span>启用</span></label></header>
          <div class="mcp-view__fields">
            <label><span>连接名称</span><input v-model.trim="draft.name" required maxlength="120" /></label>
            <label><span>传输协议</span><select v-model="draft.transport"><option value="sse">SSE</option><option value="streamable_http">Streamable HTTP</option></select></label>
            <label class="mcp-view__url"><span>Server URL</span><input v-model.trim="draft.url" type="url" required maxlength="2048" /></label>
            <label><span>超时（秒）</span><input v-model.number="draft.timeoutSeconds" type="number" min="1" max="300" required /></label>
            <label><span>重试次数</span><input v-model.number="draft.retries" type="number" min="0" max="5" required /></label>
          </div>
          <div class="mcp-view__commands">
            <button v-if="mcp.selected" type="button" :disabled="mcp.checkingId === mcp.selected.id" @click="run(() => mcp.check(mcp.selected!.id))"><RefreshCw :size="15" :class="{ spin: mcp.checkingId === mcp.selected.id }" aria-hidden="true" />{{ mcp.checkingId === mcp.selected.id ? '检查中' : '检查连接' }}</button>
            <button v-if="mcp.selected" type="button" class="mcp-view__delete" :disabled="mcp.isSaving" @click="run(() => mcp.remove(mcp.selected!.id))"><Trash2 :size="15" aria-hidden="true" />删除</button>
            <button type="submit" class="mcp-view__save" :disabled="mcp.isSaving"><Save :size="15" aria-hidden="true" />{{ mcp.isSaving ? '保存中' : '保存连接' }}</button>
          </div>
        </form>

        <section class="mcp-view__inspection" aria-label="连接检查结果">
          <header><div><p>工具发现</p><h3>Server 能力</h3></div><Cable :size="18" aria-hidden="true" /></header>
          <div v-if="mcp.selected?.lastCheck" class="mcp-view__check-summary" :class="{ 'mcp-view__check-summary--failed': !mcp.selected.lastCheck.ok }">
            <CheckCircle2 v-if="mcp.selected.lastCheck.ok" :size="17" aria-hidden="true" /><TriangleAlert v-else :size="17" aria-hidden="true" />
            <span><strong>{{ mcp.selected.lastCheck.ok ? '连接正常' : '连接异常' }}</strong><small>{{ mcp.selected.lastCheck.ok ? `发现 ${mcp.selected.lastCheck.toolCount} 个工具` : mcp.selected.lastCheck.error }}</small></span>
          </div>
          <ul v-if="mcp.selected?.lastCheck?.tools.length"><li v-for="tool in mcp.selected.lastCheck.tools" :key="tool.name"><Wrench :size="15" aria-hidden="true" /><span><strong>{{ tool.name }}</strong><small>{{ tool.description }}</small></span></li></ul>
          <p v-else class="mcp-view__empty">保存连接后执行检查，这里会展示 Server 真实返回的工具。</p>
        </section>
      </main>
    </div>
  </section>
</template>

<style scoped>
.mcp-view { background: var(--surface-raised); display: grid; grid-template-rows: auto minmax(0, 1fr); height: 100%; min-height: 0; }
.mcp-view__header { align-items: center; border-bottom: 1px solid var(--line); display: flex; justify-content: space-between; padding: 1.2rem clamp(1rem, 3vw, 2rem); }
.mcp-view__header p, .mcp-view__editor header p, .mcp-view__inspection header p { color: var(--text-tertiary); font-size: 0.7rem; font-weight: 700; margin: 0 0 0.25rem; }
.mcp-view__header h2 { font-size: 1.35rem; margin: 0; }
.mcp-view__header span { color: var(--text-secondary); display: block; font-size: 0.78rem; margin-top: 0.3rem; }
.mcp-view__header > button, .mcp-view__commands button { align-items: center; border: 1px solid var(--line-strong); border-radius: 0.4rem; display: inline-flex; font-size: 0.76rem; font-weight: 650; gap: 0.35rem; min-height: 2.2rem; padding: 0 0.7rem; }
.mcp-view__workspace { display: grid; grid-template-columns: minmax(15rem, 20rem) minmax(0, 1fr); min-height: 0; }
.mcp-view__list { border-right: 1px solid var(--line); display: grid; gap: 0.35rem; overflow-y: auto; padding: 0.75rem; }
.mcp-view__list > button { align-items: center; border-radius: 0.35rem; display: grid; gap: 0.6rem; grid-template-columns: auto minmax(0, 1fr) auto; padding: 0.7rem; text-align: left; }
.mcp-view__list > button:hover, .mcp-view__connection--active { background: var(--surface-hover); }
.mcp-view__connection-icon { align-items: center; background: var(--surface); border: 1px solid var(--line); border-radius: 0.35rem; display: inline-flex; height: 2rem; justify-content: center; width: 2rem; }
.mcp-view__list strong, .mcp-view__list small { display: block; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mcp-view__list strong { font-size: 0.8rem; }.mcp-view__list small { color: var(--text-tertiary); font-size: 0.68rem; margin-top: 0.2rem; }.mcp-view__ok { color: var(--status-success-text); }.mcp-view__bad { color: var(--status-danger-text); }
.mcp-view__editor { display: grid; grid-template-columns: minmax(24rem, 1fr) minmax(18rem, 0.72fr); min-height: 0; overflow: hidden; }
.mcp-view__editor > form, .mcp-view__inspection { min-width: 0; overflow-y: auto; padding: clamp(1rem, 3vw, 2rem); }
.mcp-view__editor > form { border-right: 1px solid var(--line); }
.mcp-view__editor header { align-items: center; display: flex; justify-content: space-between; }.mcp-view__editor h3 { font-size: 1rem; margin: 0; }
.mcp-view__toggle { align-items: center; display: flex; font-size: 0.76rem; gap: 0.4rem; }.mcp-view__toggle input { accent-color: var(--accent-strong); height: 1rem; width: 1rem; }
.mcp-view__fields { display: grid; gap: 0.9rem; grid-template-columns: repeat(2, minmax(0, 1fr)); margin-top: 1.4rem; }.mcp-view__fields label { color: var(--text-secondary); display: grid; font-size: 0.74rem; font-weight: 650; gap: 0.4rem; }.mcp-view__url { grid-column: 1 / -1; }
.mcp-view__fields input, .mcp-view__fields select { background: var(--surface); border: 1px solid var(--line-strong); border-radius: 0.4rem; color: var(--text-primary); font: inherit; min-height: 2.45rem; padding: 0 0.65rem; width: 100%; }
.mcp-view__commands { display: flex; flex-wrap: wrap; gap: 0.55rem; justify-content: flex-end; margin-top: 1.4rem; }.mcp-view__save { background: var(--accent-strong); border-color: var(--accent-strong) !important; color: white; }.mcp-view__delete { color: var(--status-danger-text); margin-right: auto; }
.mcp-view__inspection { background: #fbfbfc; }.mcp-view__check-summary { align-items: center; background: var(--status-success-bg); border: 1px solid var(--status-success-border); display: flex; gap: 0.65rem; margin-top: 1.2rem; padding: 0.75rem; }.mcp-view__check-summary--failed { background: var(--status-danger-bg); border-color: var(--status-danger-border); }.mcp-view__check-summary strong, .mcp-view__check-summary small { display: block; }.mcp-view__check-summary small { font-size: 0.7rem; margin-top: 0.15rem; }
.mcp-view__inspection ul { display: grid; gap: 0; list-style: none; margin: 1rem 0 0; padding: 0; }.mcp-view__inspection li { align-items: start; border-bottom: 1px solid var(--line); display: grid; gap: 0.55rem; grid-template-columns: auto minmax(0, 1fr); padding: 0.75rem 0; }.mcp-view__inspection li strong, .mcp-view__inspection li small { display: block; overflow-wrap: anywhere; }.mcp-view__inspection li strong { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 0.76rem; }.mcp-view__inspection li small, .mcp-view__empty { color: var(--text-tertiary); font-size: 0.72rem; line-height: 1.5; margin-top: 0.2rem; }
.spin { animation: spin 0.8s linear infinite; } @keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 1100px) { .mcp-view__editor { grid-template-columns: minmax(0, 1fr); overflow-y: auto; }.mcp-view__editor > form { border-bottom: 1px solid var(--line); border-right: 0; overflow: visible; }.mcp-view__inspection { overflow: visible; } }
@media (max-width: 760px) { .mcp-view { height: auto; }.mcp-view__header { align-items: flex-start; gap: 1rem; }.mcp-view__workspace { grid-template-columns: minmax(0, 1fr); }.mcp-view__list { border-bottom: 1px solid var(--line); border-right: 0; max-height: 15rem; }.mcp-view__editor { display: block; }.mcp-view__fields { grid-template-columns: minmax(0, 1fr); }.mcp-view__url { grid-column: auto; } }
</style>
