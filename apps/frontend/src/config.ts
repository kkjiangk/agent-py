import { apiBaseUrl } from "virtual:agent-py-public-config";

export const API_BASE_URL = resolveApiBaseUrl(apiBaseUrl);

export function resolveApiBaseUrl(apiBaseUrl: string): string {
  return apiBaseUrl.trim().replace(/\/+$/, "");
}
