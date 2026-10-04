export const KNOWLEDGE_RETRIEVAL_TOOL_NAME = "knowledge_retrieval" as const;

export const KNOWLEDGE_RETRIEVAL_TOP_K_LIMITS = {
  default: 5,
  max: 5
} as const;

export interface KnowledgeRetrievalFilters {
  readonly knowledgeBaseIds?: readonly string[];
  readonly documentIds?: readonly string[];
  readonly metadata?: Record<string, string | number | boolean>;
}

export interface KnowledgeRetrievalToolInput {
  readonly query: string;
  readonly topK?: number;
  readonly filters?: KnowledgeRetrievalFilters;
}

export interface KnowledgeRetrievalHit {
  readonly chunkId: string;
  readonly documentId: string;
  readonly knowledgeBaseId: string;
  readonly ownerUserId: string;
  readonly tenantId: string;
  readonly content: string;
  readonly source: string;
  readonly metadata: Record<string, unknown>;
  readonly score: number;
  readonly vectorRank: number | null;
  readonly bm25Rank: number | null;
  readonly rerankRank: number;
  readonly vectorScore: number | null;
  readonly bm25Score: number | null;
  readonly rrfScore: number;
  readonly rerankScore: number;
}

export interface KnowledgeRetrievalCitationSource {
  readonly id: string;
  readonly title: string;
  readonly sourceType: "knowledge-base";
  readonly chunkId: string;
  readonly documentId: string;
  readonly knowledgeBaseId: string;
  readonly source: string;
  readonly uri?: string;
  readonly metadata: Record<string, unknown>;
  readonly score: number;
  readonly vectorRank: number | null;
  readonly bm25Rank: number | null;
  readonly rerankRank: number;
  readonly vectorScore: number | null;
  readonly bm25Score: number | null;
  readonly rrfScore: number;
  readonly rerankScore: number;
}

export interface KnowledgeRetrievalToolOutput {
  readonly query: string;
  readonly topK: number;
  readonly results: readonly KnowledgeRetrievalHit[];
  readonly citations: readonly KnowledgeRetrievalCitationSource[];
}
