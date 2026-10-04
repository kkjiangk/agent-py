export interface ChatPromptAsset {
  readonly id: string;
  readonly label: string;
  readonly content: string;
  readonly isDefault: boolean;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface ChatSkillAsset {
  readonly id: string;
  readonly filename: string;
  readonly name: string;
  readonly description: string;
  readonly label: string;
  readonly contentPreview: string;
  readonly sizeBytes: number;
  readonly createdAt: string;
  readonly updatedAt: string;
}

export interface ChatAssemblySelection {
  readonly systemPromptId: string;
  readonly skillIds: readonly string[];
  readonly updatedAt: string;
}

export interface ChatAssemblyConfigurationResponse {
  readonly prompts: readonly ChatPromptAsset[];
  readonly skills: readonly ChatSkillAsset[];
  readonly selection: ChatAssemblySelection;
}

export interface UpdateChatAssemblyConfigurationRequest {
  readonly systemPromptId: string;
  readonly skillIds: readonly string[];
}

export interface CreateChatPromptRequest {
  readonly label: string;
  readonly content: string;
}

export interface UpdateChatPromptRequest {
  readonly label: string;
  readonly content: string;
}

export type ChatPromptResponse = ChatPromptAsset;

export interface DeleteChatPromptResponse {
  readonly promptId: string;
  readonly deleted: boolean;
}

export type ChatSkillUploadResponse = ChatSkillAsset;

export interface DeleteChatSkillResponse {
  readonly skillId: string;
  readonly deleted: boolean;
}
