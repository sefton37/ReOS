/**
 * TypeScript types for the block-based content system.
 * These types match the Python backend models in blocks_models.py.
 */

/**
 * Supported block types (matches Python BlockType enum).
 */
export type BlockType =
  | 'page'
  | 'paragraph'
  | 'heading_1'
  | 'heading_2'
  | 'heading_3'
  | 'bulleted_list'
  | 'numbered_list'
  | 'to_do'
  | 'code'
  | 'divider'
  | 'callout'
  | 'scene'
  | 'table'
  | 'document_chunk';

/**
 * Block types that support nesting children.
 */
export const NESTABLE_TYPES: ReadonlySet<BlockType> = new Set([
  'page',
  'bulleted_list',
  'numbered_list',
  'to_do',
  'callout',
]);

/**
 * A span of formatted text within a block.
 * Rich text is stored as a sequence of spans, each with its own formatting.
 */
export interface RichTextSpan {
  id: string;
  block_id: string;
  position: number;
  content: string;

  // Formatting flags
  bold: boolean;
  italic: boolean;
  strikethrough: boolean;
  code: boolean;
  underline: boolean;

  // Colors (optional)
  color: string | null;
  background_color: string | null;

  // Link (optional)
  link_url: string | null;
}

/**
 * A content block in the Notion-style editor.
 * Blocks form a tree structure where each block can have children.
 */
export interface Block {
  id: string;
  type: BlockType;
  act_id: string;

  // Hierarchy
  parent_id: string | null;
  page_id: string | null;
  scene_id: string | null;
  position: number;

  // Timestamps
  created_at: string;
  updated_at: string;

  // Content
  rich_text: RichTextSpan[];

  // Type-specific properties (e.g., checked for to_do, language for code)
  properties: Record<string, unknown>;

  // Children (loaded for tree operations)
  children: Block[];
}

/**
 * Create a new RichTextSpan with default values.
 */
export function createRichTextSpan(
  blockId: string,
  content: string,
  position: number = 0,
): RichTextSpan {
  return {
    id: crypto.randomUUID(),
    block_id: blockId,
    position,
    content,
    bold: false,
    italic: false,
    strikethrough: false,
    code: false,
    underline: false,
    color: null,
    background_color: null,
    link_url: null,
  };
}

/**
 * Create a new Block with default values.
 */
export function createBlock(
  type: BlockType,
  actId: string,
  pageId: string | null = null,
  parentId: string | null = null,
): Block {
  return {
    id: crypto.randomUUID(),
    type,
    act_id: actId,
    parent_id: parentId,
    page_id: pageId,
    scene_id: null,
    position: 0,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    rich_text: [],
    properties: {},
    children: [],
  };
}

/**
 * Get plain text from a block's rich_text spans.
 */
export function getBlockPlainText(block: Block): string {
  return block.rich_text.map((span) => span.content).join('');
}

/**
 * Check if a block type supports nesting.
 */
export function isNestable(type: BlockType): boolean {
  return NESTABLE_TYPES.has(type);
}

// --- RPC Response Types ---

export interface BlocksPageTreeResult {
  blocks: Block[];
}

export interface BlockCreateResult {
  block: Block;
}

export interface BlockUpdateResult {
  block: Block;
}

export interface BlocksSearchResult {
  blocks: Block[];
}

export interface UncheckedTodosResult {
  blocks: Block[];
}

// --- Editor State Types ---

export interface EditorContext {
  actId: string;
  pageId: string | null;
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
}

export interface BlockEditorProps {
  actId: string;
  pageId: string | null;
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  onSaveStatusChange?: (isSaving: boolean) => void;
}
