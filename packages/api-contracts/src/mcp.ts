export type McpTransport = "sse" | "streamable_http";

export interface McpToolSummary {
  readonly name: string;
  readonly description: string;
  readonly inputSchema: Record<string, unknown>;
  readonly serverName: string;
}

export interface McpConnectionCheck {
  readonly ok: boolean;
  readonly toolCount: number;
  readonly tools: readonly McpToolSummary[];
  readonly error: string | null;
  readonly checkedAt: string | null;
}

export interface McpConnection {
  readonly id: string;
  readonly ownerUserId: string;
  readonly name: string;
  readonly transport: McpTransport;
  readonly url: string;
  readonly enabled: boolean;
  readonly timeoutSeconds: number;
  readonly retries: number;
  readonly lastCheck: McpConnectionCheck | null;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface McpConnectionMutationRequest {
  readonly name: string;
  readonly transport: McpTransport;
  readonly url: string;
  readonly enabled: boolean;
  readonly timeoutSeconds: number;
  readonly retries: number;
}

export interface McpConnectionListResponse {
  readonly items: readonly McpConnection[];
}

export interface McpConnectionCheckResponse {
  readonly connection: McpConnection;
  readonly tools: readonly McpToolSummary[];
}

export interface DeleteMcpConnectionResponse {
  readonly deleted: true;
  readonly connectionId: string;
}
