export interface VectorChunkMetadata {
  readonly ownerUserId: string;
  readonly tenantId: string;
  readonly knowledgeBaseId: string;
  readonly documentId: string;
  readonly chunkId: string;
}

export interface BuildVectorChunkMetadataInput {
  readonly ownerUserId: string;
  readonly tenantId: string;
  readonly knowledgeBaseId: string;
  readonly documentId: string;
  readonly chunkId: string;
}

export interface BuildMilvusTenantFilterInput {
  readonly tenantId: string;
  readonly knowledgeBaseIds: readonly string[];
}

export function buildVectorChunkMetadata(input: BuildVectorChunkMetadataInput): VectorChunkMetadata {
  return {
    ownerUserId: input.ownerUserId,
    tenantId: input.tenantId,
    knowledgeBaseId: input.knowledgeBaseId,
    documentId: input.documentId,
    chunkId: input.chunkId
  };
}

export function buildMilvusTenantFilter(input: BuildMilvusTenantFilterInput): string {
  const quotedKnowledgeBaseIds = input.knowledgeBaseIds
    .map((knowledgeBaseId) => `"${escapeMilvusString(knowledgeBaseId)}"`)
    .join(",");
  return `tenantId == "${escapeMilvusString(input.tenantId)}" && knowledgeBaseId in [${quotedKnowledgeBaseIds}]`;
}

function escapeMilvusString(value: string): string {
  return value.replaceAll("\\", "\\\\").replaceAll('"', '\\"');
}
