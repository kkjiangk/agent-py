import type {
  DeleteMcpConnectionResponse,
  McpConnection,
  McpConnectionCheckResponse,
  McpConnectionListResponse,
  McpConnectionMutationRequest
} from "@agent-py/api-contracts";

import { createApiClient } from "../api/apiClient";
import { AUTH_TOKEN_STORAGE_KEY } from "../authClient";
import { API_BASE_URL } from "../config";

export interface McpClient {
  check(connectionId: string): Promise<McpConnectionCheckResponse>;
  create(request: McpConnectionMutationRequest): Promise<McpConnection>;
  delete(connectionId: string): Promise<DeleteMcpConnectionResponse>;
  list(): Promise<McpConnectionListResponse>;
  update(connectionId: string, request: McpConnectionMutationRequest): Promise<McpConnection>;
}

export function createMcpClient(): McpClient {
  const api = createApiClient({
    baseUrl: API_BASE_URL,
    getAccessToken: () => window.localStorage.getItem(AUTH_TOKEN_STORAGE_KEY)
  });
  return {
    check: (connectionId) =>
      api.request<McpConnectionCheckResponse>(`/mcp/connections/${connectionId}:check`, {
        method: "POST"
      }),
    create: (request) =>
      api.request<McpConnection>("/mcp/connections", {
        body: JSON.stringify(request),
        method: "POST"
      }),
    delete: (connectionId) =>
      api.request<DeleteMcpConnectionResponse>(`/mcp/connections/${connectionId}`, {
        method: "DELETE"
      }),
    list: () => api.request<McpConnectionListResponse>("/mcp/connections"),
    update: (connectionId, request) =>
      api.request<McpConnection>(`/mcp/connections/${connectionId}`, {
        body: JSON.stringify(request),
        method: "PUT"
      })
  };
}
