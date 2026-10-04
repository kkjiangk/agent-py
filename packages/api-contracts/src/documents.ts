export type KnowledgeDocumentStatus = "ready" | "deleted";
export type KnowledgeDocumentIndexStatus = "pending" | "indexing" | "indexed" | "failed";
export type DocumentChunkingStrategy = "fixed-character" | "markdown-heading" | "paragraph";

export interface FixedCharacterChunkingConfiguration {
  readonly strategy: "fixed-character";
  readonly maxCharacters: number;
  readonly overlapCharacters: number;
}

export interface MarkdownHeadingChunkingConfiguration {
  readonly strategy: "markdown-heading";
}

export interface ParagraphChunkingConfiguration {
  readonly strategy: "paragraph";
}

export type DocumentChunkingConfiguration =
  | FixedCharacterChunkingConfiguration
  | MarkdownHeadingChunkingConfiguration
  | ParagraphChunkingConfiguration;

export interface DocumentChunkPreviewItem {
  readonly index: number;
  readonly characterCount: number;
  readonly excerpt: string;
  readonly headingPath?: string;
}

export interface DocumentChunkPreview {
  readonly configuration: DocumentChunkingConfiguration;
  readonly totalChunks: number;
  readonly truncated: boolean;
  readonly items: readonly DocumentChunkPreviewItem[];
}

export const DOCUMENT_UPLOAD_POLICY = {
  maxSizeBytes: 10 * 1024 * 1024,
  allowedMimeTypes: [
    "application/pdf",
    "application/octet-stream",
    "text/markdown",
    "text/plain"
  ],
  allowedExtensions: [".md", ".pdf"],
  duplicateWithoutOverwrite: "conflict",
  overwriteField: "overwrite"
} as const;

export interface KnowledgeDocument {
  readonly id: string;
  readonly knowledgeBaseId: string;
  readonly ownerUserId: string;
  readonly filename: string;
  readonly sizeBytes: number;
  readonly mimeType: string;
  readonly contentHash: string;
  readonly status: KnowledgeDocumentStatus;
  readonly indexStatus: KnowledgeDocumentIndexStatus;
  readonly chunking?: DocumentChunkingConfiguration;
  readonly uploadedAt: string;
  readonly updatedAt: string;
  readonly source?: string | null;
}

export interface KnowledgeDocumentListResponse {
  readonly items: readonly KnowledgeDocument[];
}

export interface KnowledgeDocumentUploadResponse {
  readonly document: KnowledgeDocument;
  readonly duplicateOfDocumentId: string | null;
  readonly overwrite: boolean;
}

export interface KnowledgeDocumentDeleteResponse {
  readonly deleted: true;
  readonly documentId: string;
}

export interface KnowledgeDocumentChunkPreviewResponse {
  readonly preview: DocumentChunkPreview;
}
