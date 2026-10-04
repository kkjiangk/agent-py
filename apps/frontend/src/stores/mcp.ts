import { computed, ref } from "vue";
import { defineStore } from "pinia";

import type { McpConnection, McpConnectionMutationRequest } from "@agent-py/api-contracts";

import { createMcpClient } from "../mcp/mcpClient";
import { toUserFacingError } from "../ui/userFacingError";
import { useFeedbackStore } from "./feedback";

export const useMcpStore = defineStore("mcp", () => {
  const client = createMcpClient();
  const connections = ref<readonly McpConnection[]>([]);
  const selectedId = ref<string | null>(null);
  const isLoading = ref(false);
  const isSaving = ref(false);
  const checkingId = ref<string | null>(null);
  const selected = computed(
    () => connections.value.find((item) => item.id === selectedId.value) ?? null
  );

  function report(error: unknown): void {
    useFeedbackStore().showError(toUserFacingError(error));
  }

  function upsert(connection: McpConnection): void {
    connections.value = [
      ...connections.value.filter((item) => item.id !== connection.id),
      connection
    ];
    selectedId.value = connection.id;
  }

  async function initialize(): Promise<void> {
    isLoading.value = true;
    try {
      const response = await client.list();
      connections.value = response.items;
      selectedId.value ??= response.items[0]?.id ?? null;
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isLoading.value = false;
    }
  }

  async function create(request: McpConnectionMutationRequest): Promise<void> {
    isSaving.value = true;
    try {
      upsert(await client.create(request));
      useFeedbackStore().show("success", "MCP 连接已创建");
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isSaving.value = false;
    }
  }

  async function update(request: McpConnectionMutationRequest): Promise<void> {
    if (selectedId.value === null) return;
    isSaving.value = true;
    try {
      upsert(await client.update(selectedId.value, request));
      useFeedbackStore().show("success", "MCP 连接已保存");
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isSaving.value = false;
    }
  }

  async function check(connectionId: string): Promise<void> {
    checkingId.value = connectionId;
    try {
      const response = await client.check(connectionId);
      upsert(response.connection);
      useFeedbackStore().show(
        response.connection.lastCheck?.ok ? "success" : "error",
        response.connection.lastCheck?.ok
          ? `连接正常，发现 ${response.tools.length} 个工具`
          : response.connection.lastCheck?.error ?? "MCP 连接检查失败"
      );
    } catch (error) {
      report(error);
      throw error;
    } finally {
      checkingId.value = null;
    }
  }

  async function remove(connectionId: string): Promise<void> {
    isSaving.value = true;
    try {
      await client.delete(connectionId);
      connections.value = connections.value.filter((item) => item.id !== connectionId);
      selectedId.value = connections.value[0]?.id ?? null;
      useFeedbackStore().show("success", "MCP 连接已删除");
    } catch (error) {
      report(error);
      throw error;
    } finally {
      isSaving.value = false;
    }
  }

  return {
    checkingId,
    connections,
    isLoading,
    isSaving,
    selected,
    selectedId,
    check,
    create,
    initialize,
    remove,
    select: (connectionId: string) => { selectedId.value = connectionId; },
    update
  };
});
