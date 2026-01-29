import { useEditor, EditorContent, ReactRenderer } from '@tiptap/react';
import StarterKit from '@tiptap/starter-kit';
import Placeholder from '@tiptap/extension-placeholder';
import Link from '@tiptap/extension-link';
import TaskList from '@tiptap/extension-task-list';
import TaskItem from '@tiptap/extension-task-item';
import Table from '@tiptap/extension-table';
import TableRow from '@tiptap/extension-table-row';
import TableHeader from '@tiptap/extension-table-header';
import TableCell from '@tiptap/extension-table-cell';
import { useCallback, useEffect, useState, useRef } from 'react';
import tippy, { Instance as TippyInstance } from 'tippy.js';
import type { BlockEditorProps, Block, RichTextSpan } from './types';
import { useDebounce } from './hooks/useDebounce';
import { SlashCommand } from './extensions/SlashCommand';
import { DocumentNode } from './extensions/DocumentNode';
import { SlashMenu, type SlashMenuHandle } from './commands/SlashMenu';
import { slashCommands, filterCommands, type SlashCommandContext } from './commands/slashCommands';
import { FormattingToolbar } from './toolbar/FormattingToolbar';
import { TableContextMenu } from './components/TableContextMenu';

// Styles for the editor
const editorStyles = `
  .block-editor {
    flex: 1;
    display: flex;
    flex-direction: column;
    min-height: 300px;
    background: rgba(0, 0, 0, 0.2);
    border: 2px solid rgba(255, 255, 255, 0.15);
    border-radius: 12px;
    padding: 20px;
    overflow-y: auto;
    transition: border-color 0.2s, box-shadow 0.2s;
  }

  .block-editor:focus-within {
    border-color: rgba(34, 197, 94, 0.5);
    box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.1);
  }

  .block-editor .ProseMirror {
    flex: 1;
    outline: none;
    color: #e5e7eb;
    font-family: 'Inter', system-ui, sans-serif;
    font-size: 14px;
    line-height: 1.7;
  }

  .block-editor .ProseMirror p {
    margin: 0 0 0.5em 0;
  }

  .block-editor .ProseMirror h1 {
    font-size: 1.75em;
    font-weight: 700;
    margin: 1em 0 0.5em 0;
    color: #f3f4f6;
  }

  .block-editor .ProseMirror h2 {
    font-size: 1.5em;
    font-weight: 600;
    margin: 0.8em 0 0.4em 0;
    color: #f3f4f6;
  }

  .block-editor .ProseMirror h3 {
    font-size: 1.25em;
    font-weight: 600;
    margin: 0.6em 0 0.3em 0;
    color: #f3f4f6;
  }

  .block-editor .ProseMirror ul,
  .block-editor .ProseMirror ol {
    padding-left: 1.5em;
    margin: 0.5em 0;
  }

  .block-editor .ProseMirror li {
    margin: 0.2em 0;
  }

  .block-editor .ProseMirror ul[data-type="taskList"] {
    list-style: none;
    padding-left: 0;
  }

  .block-editor .ProseMirror ul[data-type="taskList"] li {
    display: flex;
    align-items: flex-start;
    gap: 8px;
  }

  .block-editor .ProseMirror ul[data-type="taskList"] li > label {
    margin-top: 4px;
  }

  .block-editor .ProseMirror ul[data-type="taskList"] li > label input[type="checkbox"] {
    width: 16px;
    height: 16px;
    cursor: pointer;
    accent-color: #22c55e;
  }

  .block-editor .ProseMirror ul[data-type="taskList"] li > div {
    flex: 1;
  }

  .block-editor .ProseMirror ul[data-type="taskList"] li[data-checked="true"] > div {
    text-decoration: line-through;
    opacity: 0.6;
  }

  .block-editor .ProseMirror blockquote {
    border-left: 3px solid rgba(34, 197, 94, 0.5);
    padding-left: 1em;
    margin: 0.5em 0;
    color: rgba(255, 255, 255, 0.7);
    font-style: italic;
  }

  .block-editor .ProseMirror code {
    background: rgba(0, 0, 0, 0.3);
    padding: 0.2em 0.4em;
    border-radius: 4px;
    font-family: 'JetBrains Mono', 'Fira Code', monospace;
    font-size: 0.9em;
  }

  .block-editor .ProseMirror pre {
    background: rgba(0, 0, 0, 0.4);
    padding: 12px 16px;
    border-radius: 8px;
    overflow-x: auto;
    margin: 0.5em 0;
  }

  .block-editor .ProseMirror pre code {
    background: none;
    padding: 0;
    border-radius: 0;
    font-size: 0.85em;
    line-height: 1.5;
  }

  .block-editor .ProseMirror hr {
    border: none;
    border-top: 1px solid rgba(255, 255, 255, 0.15);
    margin: 1em 0;
  }

  .block-editor .ProseMirror a {
    color: #60a5fa;
    text-decoration: underline;
    cursor: pointer;
  }

  .block-editor .ProseMirror a:hover {
    color: #93c5fd;
  }

  .block-editor .ProseMirror strong {
    font-weight: 600;
    color: #f9fafb;
  }

  .block-editor .ProseMirror em {
    font-style: italic;
  }

  .block-editor .ProseMirror s {
    text-decoration: line-through;
    opacity: 0.7;
  }

  .block-editor .ProseMirror p.is-editor-empty:first-child::before {
    content: attr(data-placeholder);
    float: left;
    color: rgba(255, 255, 255, 0.5);
    pointer-events: none;
    height: 0;
    font-style: italic;
  }

  .block-editor .ProseMirror {
    cursor: text;
  }

  .block-editor .ProseMirror:focus {
    outline: none;
  }

  .block-editor-status {
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 8px 0;
    font-size: 12px;
    color: rgba(255, 255, 255, 0.4);
  }

  .block-editor-status.saving {
    color: #f59e0b;
  }

  .block-editor-status.saved {
    color: #22c55e;
  }

  .block-editor-status.error {
    color: #ef4444;
  }

  /* Table styles */
  .block-editor .ProseMirror table {
    border-collapse: collapse;
    table-layout: fixed;
    width: 100%;
    margin: 1em 0;
    overflow: hidden;
  }

  .block-editor .ProseMirror td,
  .block-editor .ProseMirror th {
    min-width: 1em;
    border: 1px solid rgba(255, 255, 255, 0.2);
    padding: 8px 12px;
    vertical-align: top;
    box-sizing: border-box;
    position: relative;
  }

  .block-editor .ProseMirror th {
    font-weight: 600;
    text-align: left;
    background: rgba(255, 255, 255, 0.08);
    color: #f3f4f6;
  }

  .block-editor .ProseMirror td {
    background: rgba(0, 0, 0, 0.1);
  }

  .block-editor .ProseMirror .selectedCell:after {
    z-index: 2;
    position: absolute;
    content: "";
    left: 0; right: 0; top: 0; bottom: 0;
    background: rgba(34, 197, 94, 0.15);
    pointer-events: none;
  }

  .block-editor .ProseMirror .column-resize-handle {
    position: absolute;
    right: -2px;
    top: 0;
    bottom: -2px;
    width: 4px;
    background-color: rgba(34, 197, 94, 0.5);
    pointer-events: none;
  }

  .block-editor .ProseMirror.resize-cursor {
    cursor: ew-resize;
    cursor: col-resize;
  }

  /* Table context menu */
  .table-context-menu {
    position: fixed;
    background: #1f2937;
    border: 1px solid rgba(255, 255, 255, 0.15);
    border-radius: 8px;
    padding: 4px 0;
    min-width: 180px;
    box-shadow: 0 10px 25px rgba(0, 0, 0, 0.4);
    z-index: 1000;
  }

  .table-context-menu-item {
    padding: 8px 16px;
    cursor: pointer;
    color: #e5e7eb;
    font-size: 13px;
    display: flex;
    align-items: center;
    gap: 8px;
  }

  .table-context-menu-item:hover {
    background: rgba(255, 255, 255, 0.1);
  }

  .table-context-menu-item.danger {
    color: #ef4444;
  }

  .table-context-menu-divider {
    height: 1px;
    background: rgba(255, 255, 255, 0.1);
    margin: 4px 0;
  }
`;

interface BlocksPageTreeResult {
  blocks: Block[];
}

/**
 * Table data structure for markdown conversion.
 */
interface TableData {
  headers: string[];
  rows: string[][];
}

/**
 * Extract table data from a TipTap table node for markdown conversion.
 */
function extractTableData(tableNode: Record<string, unknown>): TableData {
  const tableContent = tableNode.content as Array<Record<string, unknown>> | undefined;
  const headers: string[] = [];
  const rows: string[][] = [];

  if (!tableContent) return { headers, rows };

  for (let rowIndex = 0; rowIndex < tableContent.length; rowIndex++) {
    const row = tableContent[rowIndex];
    const rowContent = row.content as Array<Record<string, unknown>> | undefined;
    if (!rowContent) continue;

    const cells: string[] = [];
    for (const cell of rowContent) {
      const cellType = cell.type as string;
      const cellContent = cell.content as Array<Record<string, unknown>> | undefined;

      // Extract text from cell content
      let cellText = '';
      if (cellContent) {
        for (const paragraph of cellContent) {
          const paragraphContent = paragraph.content as Array<Record<string, unknown>> | undefined;
          if (paragraphContent) {
            for (const textNode of paragraphContent) {
              if (textNode.type === 'text') {
                cellText += textNode.text as string || '';
              }
            }
          }
        }
      }
      cells.push(cellText);

      // First row with tableHeader cells is the header row
      if (rowIndex === 0 && cellType === 'tableHeader') {
        headers.push(cellText);
      }
    }

    // If we found headers, the first row is already processed
    if (headers.length > 0 && rowIndex === 0) {
      continue;
    }

    rows.push(cells);
  }

  // If no explicit headers found, treat first row as headers
  if (headers.length === 0 && rows.length > 0) {
    headers.push(...rows.shift()!);
  }

  return { headers, rows };
}


/**
 * Convert TipTap JSON to blocks format for backend storage.
 */
function tiptapToBlocks(
  json: Record<string, unknown>,
  actId: string,
  pageId: string | null,
): Block[] {
  const blocks: Block[] = [];
  const content = json.content as Array<Record<string, unknown>> | undefined;

  if (!content) return blocks;

  let position = 0;
  for (const node of content) {
    const nodeType = node.type as string;

    // Handle lists specially - extract each list item as a separate block
    if (nodeType === 'bulletList' || nodeType === 'orderedList' || nodeType === 'taskList') {
      const listItems = node.content as Array<Record<string, unknown>> | undefined;
      //(`[tiptapToBlocks] Found ${nodeType} with ${listItems?.length ?? 0} items`);
      if (listItems) {
        for (let idx = 0; idx < listItems.length; idx++) {
          const item = listItems[idx];
          //(`[tiptapToBlocks] Item ${idx}: ${JSON.stringify(item).substring(0, 300)}`);
          const block = listItemToBlock(item, nodeType, actId, pageId, position);
          if (block) {
            //(`[tiptapToBlocks] Block rich_text: ${JSON.stringify(block.rich_text).substring(0, 200)}`);
            blocks.push(block);
            position++;
          } else {
            //(`[tiptapToBlocks] listItemToBlock returned null for item ${idx}`);
          }
        }
      }
      continue;
    }

    const block = nodeToBlock(node, actId, pageId, null, position);
    if (block) {
      blocks.push(block);
      position++;
    }
  }

  return blocks;
}

/**
 * Recursively extract text nodes from any TipTap content structure.
 */
function extractTextFromContent(
  content: Array<Record<string, unknown>> | undefined,
  blockId: string,
  richText: RichTextSpan[],
  spanPositionRef: { value: number },
): void {
  if (!content) return;

  for (const node of content) {
    const nodeType = node.type as string;

    if (nodeType === 'text') {
      // Direct text node
      const text = node.text as string;
      if (text) {
        const marks = (node.marks || []) as Array<{ type: string; attrs?: Record<string, unknown> }>;

        const span: RichTextSpan = {
          id: crypto.randomUUID(),
          block_id: blockId,
          position: spanPositionRef.value,
          content: text,
          bold: marks.some((m) => m.type === 'bold'),
          italic: marks.some((m) => m.type === 'italic'),
          strikethrough: marks.some((m) => m.type === 'strike'),
          code: marks.some((m) => m.type === 'code'),
          underline: marks.some((m) => m.type === 'underline'),
          color: null,
          background_color: null,
          link_url: marks.find((m) => m.type === 'link')?.attrs?.href as string | null ?? null,
        };

        richText.push(span);
        spanPositionRef.value++;
      }
    } else if (node.content) {
      // Recurse into nested content (paragraph, etc.)
      extractTextFromContent(
        node.content as Array<Record<string, unknown>>,
        blockId,
        richText,
        spanPositionRef,
      );
    }
  }
}

/**
 * Convert a list item (listItem or taskItem) to a Block.
 */
function listItemToBlock(
  item: Record<string, unknown>,
  listType: string,
  actId: string,
  pageId: string | null,
  position: number,
): Block | null {
  const itemType = item.type as string;
  const itemAttrs = (item.attrs || {}) as Record<string, unknown>;
  const itemContent = item.content as Array<Record<string, unknown>> | undefined;

  // Log the item structure for debugging
  //(`[listItemToBlock] item structure: ${JSON.stringify(item).substring(0, 500)}`);

  // Determine block type based on list type
  let blockType: Block['type'];
  const properties: Record<string, unknown> = {};

  if (listType === 'taskList' || itemType === 'taskItem') {
    blockType = 'to_do';
    properties.checked = itemAttrs.checked ?? false;
  } else if (listType === 'orderedList') {
    blockType = 'numbered_list';
  } else {
    blockType = 'bulleted_list';
  }

  const blockId = crypto.randomUUID();
  const richText: RichTextSpan[] = [];

  // Recursively extract all text from the list item content
  const spanPositionRef = { value: 0 };
  extractTextFromContent(itemContent, blockId, richText, spanPositionRef);

  //(`[listItemToBlock] extracted ${richText.length} spans: ${richText.map(s => s.content).join('|')}`);

  return {
    id: blockId,
    type: blockType,
    act_id: actId,
    parent_id: null,
    page_id: pageId,
    scene_id: null,
    position,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    rich_text: richText,
    properties,
    children: [],
  };
}

/**
 * Convert a single TipTap node to a Block.
 */
function nodeToBlock(
  node: Record<string, unknown>,
  actId: string,
  pageId: string | null,
  parentId: string | null,
  position: number,
): Block | null {
  const nodeType = node.type as string;
  const nodeAttrs = (node.attrs || {}) as Record<string, unknown>;
  const nodeContent = node.content as Array<Record<string, unknown>> | undefined;

  let blockType: Block['type'];
  const properties: Record<string, unknown> = {};
  const richText: RichTextSpan[] = [];

  switch (nodeType) {
    case 'paragraph':
      blockType = 'paragraph';
      break;
    case 'heading':
      const level = nodeAttrs.level as number;
      blockType = level === 1 ? 'heading_1' : level === 2 ? 'heading_2' : 'heading_3';
      break;
    case 'bulletList':
    case 'orderedList':
    case 'taskList':
    case 'taskItem':
    case 'listItem':
      // Lists are handled specially in tiptapToBlocks
      return null;
    case 'codeBlock':
      blockType = 'code';
      properties.language = nodeAttrs.language ?? 'text';
      break;
    case 'horizontalRule':
      blockType = 'divider';
      break;
    case 'blockquote':
      blockType = 'callout';
      break;
    case 'table':
      blockType = 'table';
      // Store table structure in properties for markdown conversion
      properties.tableData = extractTableData(node);
      break;
    case 'tableRow':
    case 'tableHeader':
    case 'tableCell':
      // These are handled by the table parent
      return null;
    default:
      // Skip unknown node types
      return null;
  }

  const blockId = crypto.randomUUID();

  // Extract text content into rich text spans (recursively handles nested structures)
  const spanPositionRef = { value: 0 };
  extractTextFromContent(nodeContent, blockId, richText, spanPositionRef);

  return {
    id: blockId,
    type: blockType,
    act_id: actId,
    parent_id: parentId,
    page_id: pageId,
    scene_id: null,
    position,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    rich_text: richText,
    properties,
    children: [],
  };
}

/**
 * Convert blocks to TipTap JSON format.
 */
function blocksToTiptap(blocks: Block[]): Record<string, unknown> {
  const content: Array<Record<string, unknown>> = [];

  for (const block of blocks) {
    const node = blockToNode(block);
    if (node) {
      content.push(node);
    }
  }

  return {
    type: 'doc',
    content: content.length > 0 ? content : [{ type: 'paragraph' }],
  };
}

/**
 * Convert a single Block to a TipTap node.
 */
function blockToNode(block: Block): Record<string, unknown> | null {
  const textContent = richTextToNodes(block.rich_text);

  switch (block.type) {
    case 'paragraph':
      return {
        type: 'paragraph',
        content: textContent,
      };

    case 'heading_1':
      return {
        type: 'heading',
        attrs: { level: 1 },
        content: textContent,
      };

    case 'heading_2':
      return {
        type: 'heading',
        attrs: { level: 2 },
        content: textContent,
      };

    case 'heading_3':
      return {
        type: 'heading',
        attrs: { level: 3 },
        content: textContent,
      };

    case 'bulleted_list':
      return {
        type: 'bulletList',
        content: block.children.map((child) => ({
          type: 'listItem',
          content: [
            {
              type: 'paragraph',
              content: richTextToNodes(child.rich_text),
            },
          ],
        })),
      };

    case 'numbered_list':
      return {
        type: 'orderedList',
        content: block.children.map((child) => ({
          type: 'listItem',
          content: [
            {
              type: 'paragraph',
              content: richTextToNodes(child.rich_text),
            },
          ],
        })),
      };

    case 'to_do':
      return {
        type: 'taskList',
        content: [
          {
            type: 'taskItem',
            attrs: { checked: block.properties.checked ?? false },
            content: textContent.length > 0 ? textContent : undefined,
          },
        ],
      };

    case 'code':
      const codeText = block.rich_text.map((s) => s.content).join('');
      return {
        type: 'codeBlock',
        attrs: { language: block.properties.language ?? 'text' },
        content: codeText ? [{ type: 'text', text: codeText }] : undefined,
      };

    case 'divider':
      return {
        type: 'horizontalRule',
      };

    case 'callout':
      return {
        type: 'blockquote',
        content: [
          {
            type: 'paragraph',
            content: textContent,
          },
        ],
      };

    default:
      return null;
  }
}

/**
 * Convert rich text spans to TipTap text nodes with marks.
 */
function richTextToNodes(spans: RichTextSpan[]): Array<Record<string, unknown>> {
  return spans.map((span) => {
    const marks: Array<{ type: string; attrs?: Record<string, unknown> }> = [];

    if (span.bold) marks.push({ type: 'bold' });
    if (span.italic) marks.push({ type: 'italic' });
    if (span.strikethrough) marks.push({ type: 'strike' });
    if (span.code) marks.push({ type: 'code' });
    if (span.underline) marks.push({ type: 'underline' });
    if (span.link_url) marks.push({ type: 'link', attrs: { href: span.link_url } });

    return {
      type: 'text',
      text: span.content,
      marks: marks.length > 0 ? marks : undefined,
    };
  });
}

export function BlockEditor({
  actId,
  pageId,
  kernelRequest,
  onSaveStatusChange,
}: BlockEditorProps) {
  console.log(`[BlockEditor] RENDER: actId=${actId}`);
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [initialContent, setInitialContent] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  // Track the hash of the last loaded/saved content to detect actual changes
  const lastSavedHashRef = useRef<string | null>(null);
  // Track whether we've received the first update after setting content
  const skipNextUpdateRef = useRef(false);
  // Track whether initial content has been loaded - BLOCK ALL SAVES until this is true
  const hasLoadedContentRef = useRef(false);
  // Track the length of originally loaded content - used as safety check against accidental overwrites
  const loadedContentLengthRef = useRef<number>(0);

  // Context for slash commands that need kernel access
  const slashCommandContextRef = useRef<SlashCommandContext>({
    kernelRequest,
    actId,
  });

  // Keep context ref up to date
  useEffect(() => {
    slashCommandContextRef.current = { kernelRequest, actId };
  }, [kernelRequest, actId]);

  // Track if load has been initiated to prevent StrictMode double-load
  const loadInitiatedRef = useRef<string | null>(null);

  // Load blocks from backend
  useEffect(() => {
    // Prevent StrictMode double-execution for the same actId
    const loadKey = `${actId}-${pageId}`;
    if (loadInitiatedRef.current === loadKey) {
      void kernelRequest('debug/log', { msg: `LOAD SKIPPED: already initiated for ${loadKey}` }).catch(() => {});
      return;
    }
    loadInitiatedRef.current = loadKey;

    async function loadBlocks() {
      // If no actId, show empty editor for The Play overview
      if (!actId) {
        setInitialContent({ type: 'doc', content: [{ type: 'paragraph' }] });
        setLoading(false);
        return;
      }

      // If no pageId, try to load the Act's kb.md content
      if (!pageId) {
        try {
          console.log(`[BlockEditor] ========== LOADING ==========`);
          console.log(`[BlockEditor] Loading kb.md for act: "${actId}"`);
          const result = (await kernelRequest('play/kb/read', {
            act_id: actId,
            path: 'kb.md',
          })) as { text: string };

          const markdown = result.text || '';
          // Send diagnostic to backend so we can see it in terminal
          void kernelRequest('debug/log', {
            msg: `LOADED MARKDOWN: ${markdown.length} chars`
          }).catch(() => {});
          void kernelRequest('debug/log', {
            msg: `FIRST 300 CHARS: ${markdown.substring(0, 300).replace(/\n/g, '\\n')}`
          }).catch(() => {});
          void kernelRequest('debug/log', {
            msg: `LINE COUNT: ${markdown.split('\n').length}, empty lines: ${markdown.split('\n').filter(l => !l.trim()).length}`
          }).catch(() => {});

          // Track loaded content length for safety checks
          loadedContentLengthRef.current = markdown.length;
          const content = markdownToTiptap(markdown);
          // Log parsed content structure
          const contentNodes = (content.content as Array<unknown>)?.length || 0;
          void kernelRequest('debug/log', {
            msg: `PARSED TO: ${contentNodes} TipTap nodes`
          }).catch(() => {});

          // Log first 3 nodes in detail
          const nodes = (content.content as Array<Record<string, unknown>>) || [];
          for (let i = 0; i < Math.min(3, nodes.length); i++) {
            void kernelRequest('debug/log', {
              msg: `NODE[${i}]: ${JSON.stringify(nodes[i]).substring(0, 200)}`
            }).catch(() => {});
          }

          console.log(`[BlockEditor] Parsed to TipTap, content nodes: ${JSON.stringify(content).substring(0, 300)}`);
          setInitialContent(content);
        } catch (e) {
          // Fail gracefully - just show empty editor
          console.error('[BlockEditor] FAILED to load kb.md:', e);
          setInitialContent({ type: 'doc', content: [{ type: 'paragraph' }] });
        } finally {
          setLoading(false);
        }
        return;
      }

      // Load page blocks
      try {
        const result = (await kernelRequest('blocks/page/tree', {
          page_id: pageId,
        })) as BlocksPageTreeResult;

        const blocks = result.blocks ?? [];
        const tiptapContent = blocksToTiptap(blocks);
        setInitialContent(tiptapContent);
      } catch {
        // Fail gracefully - just show empty editor
        setInitialContent({ type: 'doc', content: [{ type: 'paragraph' }] });
      } finally {
        setLoading(false);
      }
    }

    setLoading(true);
    setLoadError(null);
    // Reset saved hash on new load - will be set properly in the setContent useEffect
    lastSavedHashRef.current = null;
    // Block saves until content is loaded
    hasLoadedContentRef.current = false;
    // Reset loaded content length
    loadedContentLengthRef.current = 0;
    console.log(`[BlockEditor] LOAD EFFECT START: actId=${actId}, reset hasLoaded=false, loadedLen=0`);

    // Timeout to prevent infinite loading - fail gracefully after 5s
    const timeout = setTimeout(() => {
      setLoading(false);
      setInitialContent({ type: 'doc', content: [{ type: 'paragraph' }] });
    }, 5000);

    loadBlocks()
      .catch(() => {
        // Fail gracefully
        setInitialContent({ type: 'doc', content: [{ type: 'paragraph' }] });
      })
      .finally(() => {
        clearTimeout(timeout);
        setLoading(false);
      });

    return () => {
      clearTimeout(timeout);
      // Reset so a new mount with different actId can load
      loadInitiatedRef.current = null;
    };
  }, [actId, pageId, kernelRequest]);

  // Simple hash function for change detection
  const hashContent = useCallback((json: Record<string, unknown>): string => {
    return JSON.stringify(json);
  }, []);

  // Save blocks to backend
  const saveBlocks = useCallback(
    async (json: Record<string, unknown>, source: string = 'unknown') => {
      console.log(`[BlockEditor] ========== SAVE ATTEMPT (source: ${source}) ==========`);
      console.log(`[BlockEditor] actId: "${actId}", pageId: "${pageId}"`);
      console.log(`[BlockEditor] hasLoadedContent: ${hasLoadedContentRef.current}`);
      console.log(`[BlockEditor] loadedContentLength: ${loadedContentLengthRef.current}`);

      if (!actId) {
        console.warn('[BlockEditor] SKIPPED: saveBlocks called without actId');
        return;
      }

      // CRITICAL: Don't save until initial content has been loaded
      // This prevents the empty editor from overwriting real content
      if (!hasLoadedContentRef.current) {
        console.log(`[BlockEditor] SKIPPED (source: ${source}): Content not yet loaded, blocking save`);
        return;
      }

      // CRITICAL: Don't save if we haven't tracked a loaded content length yet
      // This catches edge cases where hasLoadedContentRef got set but loadedContentLengthRef didn't
      if (loadedContentLengthRef.current === 0) {
        console.log(`[BlockEditor] SKIPPED (source: ${source}): loadedContentLength is 0, blocking save`);
        return;
      }

      // Check if content actually changed by comparing hashes
      const currentHash = hashContent(json);
      console.log(`[BlockEditor] currentHash length: ${currentHash.length}, lastSavedHash length: ${lastSavedHashRef.current?.length ?? 'null'}`);
      console.log(`[BlockEditor] hashes match: ${currentHash === lastSavedHashRef.current}`);

      if (currentHash === lastSavedHashRef.current) {
        console.log('[BlockEditor] SKIPPED: Content unchanged (hash match)');
        return;
      }

      setSaveStatus('saving');
      onSaveStatusChange?.(true);

      try {
        const blocks = tiptapToBlocks(json, actId, pageId);
        const markdown = blocksToMarkdown(blocks);

        console.log(`[BlockEditor] Saving ${markdown.length} chars to act: "${actId}"`);
        console.log(`[BlockEditor] First 200 chars: ${markdown.substring(0, 200)}`);

        // SAFETY CHECK: Refuse to overwrite ANY content with essentially empty content
        // This prevents race conditions where stale empty content overwrites real content
        if (markdown.length <= 2 && loadedContentLengthRef.current > markdown.length) {
          console.error(`[BlockEditor] SAFETY BLOCK (source: ${source}): Refusing to overwrite ${loadedContentLengthRef.current} chars with ${markdown.length} chars (empty content)`);
          setSaveStatus('idle');
          onSaveStatusChange?.(false);
          return;
        }

        if (pageId) {
          console.log(`[BlockEditor] Saving to page: ${pageId}`);
          await kernelRequest('play/pages/content/write', {
            act_id: actId,
            page_id: pageId,
            text: markdown,
            _debug_source: source,
          });
        } else {
          console.log(`[BlockEditor] Saving to kb.md via preview/apply`);
          const preview = await kernelRequest('play/kb/write_preview', {
            act_id: actId,
            path: 'kb.md',
            text: markdown,
            _debug_source: source,
          }) as { sha256_current: string; sha256_new: string; diff: string };

          console.log(`[BlockEditor] Preview result - current sha: ${preview.sha256_current?.substring(0, 16)}..., new sha: ${preview.sha256_new?.substring(0, 16)}...`);

          await kernelRequest('play/kb/write_apply', {
            act_id: actId,
            path: 'kb.md',
            text: markdown,
            expected_sha256_current: preview.sha256_current,
            _debug_source: source,
          });
          console.log(`[BlockEditor] Write apply completed successfully`);
        }

        // Update the saved hash after successful save
        lastSavedHashRef.current = currentHash;

        setSaveStatus('saved');
        onSaveStatusChange?.(false);
        console.log(`[BlockEditor] ========== SAVE SUCCESS ==========`);

        // Reset to idle after a short delay
        setTimeout(() => setSaveStatus('idle'), 2000);
      } catch (e) {
        console.error('[BlockEditor] ========== SAVE FAILED ==========', e);
        setSaveStatus('error');
        onSaveStatusChange?.(false);
      }
    },
    [actId, pageId, kernelRequest, onSaveStatusChange, hashContent],
  );

  // Debounced save - flush-on-unmount disabled to prevent race conditions
  // Explicit save handlers (onBlur, visibilitychange, beforeunload) handle save-on-close
  const debouncedSave = useDebounce(saveBlocks, 500, false);

  const editor = useEditor(
    {
      editable: true,
      autofocus: 'end',
      extensions: [
        StarterKit.configure({
          heading: {
            levels: [1, 2, 3],
          },
        }),
        Placeholder.configure({
          placeholder: getPlaceholder(actId, pageId),
          showOnlyWhenEditable: true,
          showOnlyCurrent: true,
        }),
        Link.configure({
          openOnClick: true,
          HTMLAttributes: {
            target: '_blank',
            rel: 'noopener noreferrer',
          },
        }),
        TaskList,
        TaskItem.configure({
          nested: true,
        }),
        Table.configure({
          resizable: true,
          handleWidth: 5,
          cellMinWidth: 50,
          lastColumnResizable: true,
        }),
        TableRow,
        TableHeader,
        TableCell,
        DocumentNode,
        SlashCommand.configure({
          suggestion: {
            items: ({ query }: { query: string }) => {
              return filterCommands(query);
            },
            render: () => {
              let component: ReactRenderer<SlashMenuHandle> | null = null;
              let popup: TippyInstance[] | null = null;

              return {
                onStart: (props) => {
                  const editorInstance = props.editor as import('@tiptap/react').Editor;
                  component = new ReactRenderer(SlashMenu, {
                    props: {
                      ...props,
                      editor: editorInstance,
                      onClose: () => {
                        popup?.[0]?.hide();
                      },
                      position: { top: 0, left: 0 },
                      // Pass context for commands that need kernel access
                      context: slashCommandContextRef.current,
                    },
                    editor: editorInstance,
                  });

                  if (!props.clientRect) {
                    return;
                  }

                  // Use tippy for positioning
                  popup = tippy('body', {
                    getReferenceClientRect: props.clientRect as () => DOMRect,
                    appendTo: () => document.body,
                    content: component.element,
                    showOnCreate: true,
                    interactive: true,
                    trigger: 'manual',
                    placement: 'bottom-start',
                  });
                },

                onUpdate(props) {
                  // Update with latest context
                  component?.updateProps({
                    ...props,
                    context: slashCommandContextRef.current,
                  });

                  if (!props.clientRect) {
                    return;
                  }

                  popup?.[0]?.setProps({
                    getReferenceClientRect: props.clientRect as () => DOMRect,
                  });
                },

                onKeyDown(props) {
                  if (props.event.key === 'Escape') {
                    popup?.[0]?.hide();
                    return true;
                  }

                  return component?.ref?.onKeyDown(props.event) ?? false;
                },

                onExit() {
                  popup?.[0]?.destroy();
                  component?.destroy();
                },
              };
            },
          },
        }),
      ],
      content: initialContent ?? { type: 'doc', content: [{ type: 'paragraph' }] },
      onUpdate: ({ editor }) => {
        // CRITICAL: Don't start any saves until content has been loaded
        // This prevents empty editor from triggering saves that overwrite real content
        if (!hasLoadedContentRef.current) {
          console.log(`[BlockEditor] onUpdate BLOCKED: hasLoadedContent=false`);
          return;
        }
        // Skip the update triggered by setContent (loading content)
        if (skipNextUpdateRef.current) {
          skipNextUpdateRef.current = false;
          console.log(`[BlockEditor] onUpdate SKIPPED: skipNextUpdate was true`);
          return;
        }
        console.log(`[BlockEditor] onUpdate: scheduling debounced save`);
        const json = editor.getJSON();
        debouncedSave(json, 'onUpdate');
      },
      onBlur: ({ editor }) => {
        // CRITICAL: Don't save on blur until content has been loaded
        if (!hasLoadedContentRef.current) {
          console.log(`[BlockEditor] onBlur BLOCKED: hasLoadedContent=false`);
          return;
        }
        // Save immediately when editor loses focus (user clicked away)
        console.log(`[BlockEditor] onBlur: saving immediately`);
        const json = editor.getJSON();
        void saveBlocks(json, 'onBlur');
      },
      editorProps: {
        attributes: {
          class: 'ProseMirror',
        },
      },
    },
    // Empty deps - create editor once, use setContent to update
    [],
  );

  // Update content when initialContent changes
  useEffect(() => {
    if (editor && initialContent) {
      const contentArray = (initialContent.content as Array<Record<string, unknown>>) || [];
      const contentNodes = contentArray.length;
      void kernelRequest('debug/log', {
        msg: `CONTENT EFFECT: actId=${actId}, nodes=${contentNodes}, loadedLen=${loadedContentLengthRef.current}`
      }).catch(() => {});

      // Log first 3 nodes for debugging
      for (let i = 0; i < Math.min(3, contentArray.length); i++) {
        void kernelRequest('debug/log', {
          msg: `NODE[${i}]: ${JSON.stringify(contentArray[i]).substring(0, 300)}`
        }).catch(() => {});
      }

      // Set the content
      skipNextUpdateRef.current = true;
      let success = false;
      let setContentError: string | null = null;
      try {
        success = editor.commands.setContent(initialContent);
      } catch (e) {
        setContentError = String(e);
        void kernelRequest('debug/log', {
          msg: `setContent THREW: ${setContentError}`
        }).catch(() => {});
      }

      // Check what the editor actually has now
      const actualJson = editor.getJSON();
      const actualNodes = (actualJson.content as Array<unknown>)?.length || 0;
      const actualText = editor.getText();
      void kernelRequest('debug/log', {
        msg: `AFTER setContent: success=${success}, error=${setContentError}, actualNodes=${actualNodes}, textLen=${actualText.length}`
      }).catch(() => {});

      // If content failed to load, do progressive testing to find the problem
      if (actualText.length === 0 && contentNodes > 0) {
        void kernelRequest('debug/log', {
          msg: `CONTENT FAILED - starting progressive diagnostics`
        }).catch(() => {});

        // Helper to test setting content
        const testContent = (nodes: Array<Record<string, unknown>>, label: string): boolean => {
          const doc = { type: 'doc', content: nodes.length > 0 ? nodes : [{ type: 'paragraph' }] };
          try {
            editor.commands.setContent(doc);
            const text = editor.getText();
            void kernelRequest('debug/log', {
              msg: `${label}: textLen=${text.length}`
            }).catch(() => {});
            return text.length > 0;
          } catch (e) {
            void kernelRequest('debug/log', {
              msg: `${label}: THREW ${e}`
            }).catch(() => {});
            return false;
          }
        };

        // Test with increasing sizes
        const testSizes = [1, 5, 10, 50, 100];
        let lastWorking = 0;
        for (const size of testSizes) {
          if (size > contentNodes) break;
          if (testContent(contentArray.slice(0, size), `TEST ${size} nodes`)) {
            lastWorking = size;
          } else {
            void kernelRequest('debug/log', {
              msg: `BREAKS at ${size} nodes (last working: ${lastWorking})`
            }).catch(() => {});
            // Binary search to find exact problematic node
            for (let i = lastWorking; i < size && i < contentNodes; i++) {
              if (!testContent(contentArray.slice(0, i + 1), `TEST ${i + 1} nodes`)) {
                void kernelRequest('debug/log', {
                  msg: `BAD NODE[${i}]: ${JSON.stringify(contentArray[i]).substring(0, 500)}`
                }).catch(() => {});
                break;
              }
            }
            break;
          }
        }

        // If small content works, set it as fallback
        if (lastWorking > 0) {
          void kernelRequest('debug/log', {
            msg: `FALLBACK: Setting ${lastWorking} nodes that worked`
          }).catch(() => {});
          const fallbackDoc = { type: 'doc', content: contentArray.slice(0, lastWorking) };
          editor.commands.setContent(fallbackDoc);
        }
      }

      // Update the saved hash to match what was actually loaded
      const finalContent = editor.getJSON();
      lastSavedHashRef.current = JSON.stringify(finalContent);
      // NOW we can allow saves - content has been loaded (even if partially)
      hasLoadedContentRef.current = true;

      void kernelRequest('debug/log', {
        msg: `CONTENT LOAD COMPLETE: finalTextLen=${editor.getText().length}`
      }).catch(() => {});
    }
  }, [editor, initialContent, actId, kernelRequest]);

  // Save on unmount (when navigating between acts)
  // This uses the CURRENT editor content, not stale debounce args
  useEffect(() => {
    return () => {
      console.log(`[BlockEditor] UNMOUNT cleanup: editor=${!!editor}, actId=${actId}, hasLoaded=${hasLoadedContentRef.current}, loadedLen=${loadedContentLengthRef.current}`);
      if (!editor || !actId || !hasLoadedContentRef.current) {
        console.log(`[BlockEditor] UNMOUNT BLOCKED: conditions not met`);
        return;
      }
      const json = editor.getJSON();
      if (json) {
        console.log('[BlockEditor] UNMOUNT: saving');
        void saveBlocks(json, 'unmount');
      }
    };
  }, [editor, actId, saveBlocks]);

  // Save immediately on window close (beforeunload) to prevent data loss
  useEffect(() => {
    if (!editor || !actId) return;

    const handleBeforeUnload = () => {
      console.log(`[BlockEditor] beforeunload: hasLoaded=${hasLoadedContentRef.current}`);
      // Save synchronously-ish by firing the save (can't truly await in beforeunload)
      if (!hasLoadedContentRef.current) {
        console.log(`[BlockEditor] beforeunload BLOCKED`);
        return;
      }
      const json = editor.getJSON();
      if (json) {
        // Fire and forget - we can't await here
        void saveBlocks(json, 'beforeunload');
      }
    };

    // Also save when page becomes hidden (tab switch, minimize, etc.)
    const handleVisibilityChange = () => {
      console.log(`[BlockEditor] visibilitychange: state=${document.visibilityState}, hasLoaded=${hasLoadedContentRef.current}`);
      if (document.visibilityState === 'hidden' && hasLoadedContentRef.current) {
        const json = editor.getJSON();
        if (json) {
          void saveBlocks(json, 'visibilitychange');
        }
      }
    };

    window.addEventListener('beforeunload', handleBeforeUnload);
    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.removeEventListener('beforeunload', handleBeforeUnload);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [editor, actId, saveBlocks]);

  if (loading) {
    return (
      <div style={{ padding: '24px', color: 'rgba(255, 255, 255, 0.5)' }}>
        Loading...
      </div>
    );
  }

  // Debug: show state if editor isn't ready
  if (!editor) {
    return (
      <div style={{ padding: '24px', color: '#f59e0b', border: '2px solid #f59e0b', borderRadius: '8px' }}>
        Editor initializing... (initialContent: {initialContent ? 'ready' : 'null'})
      </div>
    );
  }

  return (
    <>
      <style>{editorStyles}</style>
      <div className="block-editor">
        <FormattingToolbar editor={editor} />
        <EditorContent editor={editor} />
      </div>
      <div className={`block-editor-status ${saveStatus}`}>
        {saveStatus === 'saving' && 'Saving...'}
        {saveStatus === 'saved' && 'Saved'}
        {saveStatus === 'error' && 'Error saving'}
        {saveStatus === 'idle' && <span style={{ opacity: 0.5 }}>Type / for commands</span>}
      </div>
      <TableContextMenu editor={editor} />
    </>
  );
}

/**
 * Get placeholder text based on context.
 */
function getPlaceholder(actId: string | null, pageId: string | null): string {
  if (!actId) {
    return 'This is The Play - your high-level narrative and vision...';
  }
  if (pageId) {
    return 'Write your page content here...';
  }
  return "This is the Act's script - a major chapter in your journey...";
}

/**
 * Convert blocks to markdown for storage.
 */
function blocksToMarkdown(blocks: Block[]): string {
  const lines: string[] = [];
  //(`[blocksToMarkdown] Converting ${blocks.length} blocks`);

  for (const block of blocks) {
    //(`[blocksToMarkdown] Block type=${block.type}, rich_text count=${block.rich_text.length}`);
    const text = block.rich_text.map((s) => {
      let content = s.content;
      if (s.bold) content = `**${content}**`;
      if (s.italic) content = `*${content}*`;
      if (s.code) content = `\`${content}\``;
      if (s.strikethrough) content = `~~${content}~~`;
      if (s.link_url) content = `[${content}](${s.link_url})`;
      return content;
    }).join('');

    switch (block.type) {
      case 'paragraph':
        lines.push(text);
        lines.push('');
        break;
      case 'heading_1':
        lines.push(`# ${text}`);
        lines.push('');
        break;
      case 'heading_2':
        lines.push(`## ${text}`);
        lines.push('');
        break;
      case 'heading_3':
        lines.push(`### ${text}`);
        lines.push('');
        break;
      case 'bulleted_list':
        //(`[blocksToMarkdown] bulleted_list text="${text}"`);
        lines.push(`- ${text}`);
        break;
      case 'numbered_list':
        lines.push(`1. ${text}`);
        break;
      case 'to_do':
        const checked = block.properties.checked ? 'x' : ' ';
        lines.push(`- [${checked}] ${text}`);
        break;
      case 'code':
        const lang = block.properties.language || '';
        lines.push(`\`\`\`${lang}`);
        lines.push(text);
        lines.push('```');
        lines.push('');
        break;
      case 'divider':
        lines.push('---');
        lines.push('');
        break;
      case 'callout':
        lines.push(`> ${text}`);
        lines.push('');
        break;
      case 'table':
        const tableData = block.properties.tableData as TableData | undefined;
        if (tableData && tableData.headers.length > 0) {
          // Header row
          lines.push('| ' + tableData.headers.join(' | ') + ' |');
          // Separator row
          lines.push('| ' + tableData.headers.map(() => '---').join(' | ') + ' |');
          // Data rows
          for (const row of tableData.rows) {
            // Pad row to match header length
            const paddedRow = [...row];
            while (paddedRow.length < tableData.headers.length) {
              paddedRow.push('');
            }
            lines.push('| ' + paddedRow.join(' | ') + ' |');
          }
          lines.push('');
        }
        break;
    }
  }

  return lines.join('\n');
}

/**
 * Sanitize text for TipTap - remove control characters that might break parsing.
 */
function sanitizeText(text: string): string {
  // Remove null characters and other control characters (except tab and newline)
  // eslint-disable-next-line no-control-regex
  return text.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F\x7F]/g, '');
}

/**
 * Parse inline markdown formatting and return TipTap text nodes with marks.
 * Handles: **bold**, __bold__, *italic*, _italic_, `code`, ~~strikethrough~~, [link](url)
 */
function parseInlineMarkdown(text: string): Array<Record<string, unknown>> {
  if (!text) return [];

  const nodes: Array<Record<string, unknown>> = [];

  // Regex patterns for inline formatting (order matters - more specific first)
  // Match: **bold**, __bold__, *italic*, _italic_, `code`, ~~strike~~, [text](url)
  // Note: Double markers (**/__) must come before single (*/_) to match correctly
  const inlinePattern = /(\*\*(.+?)\*\*|__(.+?)__|(?<!\*)\*([^*]+?)\*(?!\*)|(?<!_)_([^_]+?)_(?!_)|`([^`]+)`|~~(.+?)~~|\[([^\]]+)\]\(([^)]+)\))/g;

  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = inlinePattern.exec(text)) !== null) {
    // Add plain text before this match
    if (match.index > lastIndex) {
      const plainText = text.slice(lastIndex, match.index);
      if (plainText) {
        nodes.push({ type: 'text', text: plainText });
      }
    }

    const fullMatch = match[1];

    if (match[2]) {
      // **bold**
      nodes.push({
        type: 'text',
        text: match[2],
        marks: [{ type: 'bold' }],
      });
    } else if (match[3]) {
      // __bold__
      nodes.push({
        type: 'text',
        text: match[3],
        marks: [{ type: 'bold' }],
      });
    } else if (match[4]) {
      // *italic*
      nodes.push({
        type: 'text',
        text: match[4],
        marks: [{ type: 'italic' }],
      });
    } else if (match[5]) {
      // _italic_
      nodes.push({
        type: 'text',
        text: match[5],
        marks: [{ type: 'italic' }],
      });
    } else if (match[6]) {
      // `code`
      nodes.push({
        type: 'text',
        text: match[6],
        marks: [{ type: 'code' }],
      });
    } else if (match[7]) {
      // ~~strikethrough~~
      nodes.push({
        type: 'text',
        text: match[7],
        marks: [{ type: 'strike' }],
      });
    } else if (match[8] && match[9]) {
      // [link text](url)
      nodes.push({
        type: 'text',
        text: match[8],
        marks: [{ type: 'link', attrs: { href: match[9] } }],
      });
    }

    lastIndex = match.index + fullMatch.length;
  }

  // Add remaining plain text after last match
  if (lastIndex < text.length) {
    const remainingText = text.slice(lastIndex);
    if (remainingText) {
      nodes.push({ type: 'text', text: remainingText });
    }
  }

  // If no formatting found, return single text node
  if (nodes.length === 0 && text) {
    return [{ type: 'text', text }];
  }

  return nodes;
}

/**
 * Parse simple markdown into TipTap JSON format.
 */
function markdownToTiptap(markdown: string): Record<string, unknown> {
  // Normalize line endings (handle Windows \r\n and old Mac \r)
  const normalizedMarkdown = markdown.replace(/\r\n/g, '\n').replace(/\r/g, '\n');
  // Sanitize control characters
  const sanitizedMarkdown = sanitizeText(normalizedMarkdown);
  const lines = sanitizedMarkdown.split('\n');
  const content: Array<Record<string, unknown>> = [];

  let i = 0;
  while (i < lines.length) {
    const line = lines[i];

    // Skip empty lines
    if (!line.trim()) {
      i++;
      continue;
    }

    // Heading 1
    if (line.startsWith('# ')) {
      const text = line.slice(2).trim();
      if (text) {
        content.push({
          type: 'heading',
          attrs: { level: 1 },
          content: parseInlineMarkdown(text),
        });
      }
      i++;
      continue;
    }

    // Heading 2
    if (line.startsWith('## ')) {
      const text = line.slice(3).trim();
      if (text) {
        content.push({
          type: 'heading',
          attrs: { level: 2 },
          content: parseInlineMarkdown(text),
        });
      }
      i++;
      continue;
    }

    // Heading 3
    if (line.startsWith('### ')) {
      const text = line.slice(4).trim();
      if (text) {
        content.push({
          type: 'heading',
          attrs: { level: 3 },
          content: parseInlineMarkdown(text),
        });
      }
      i++;
      continue;
    }

    // Horizontal rule
    if (line.trim() === '---' || line.trim() === '***') {
      content.push({ type: 'horizontalRule' });
      i++;
      continue;
    }

    // Bullet list item
    if (line.startsWith('- ') || line.startsWith('* ')) {
      const items: Array<Record<string, unknown>> = [];
      while (i < lines.length && (lines[i].startsWith('- ') || lines[i].startsWith('* '))) {
        const rawText = lines[i].slice(2);
        // Check for todo
        if (rawText.startsWith('[ ] ') || rawText.startsWith('[x] ')) {
          const checked = rawText.startsWith('[x]');
          const text = rawText.slice(4).trim();
          // Always create task items (even empty ones - TipTap allows this)
          const inlineContent = parseInlineMarkdown(text);
          items.push({
            type: 'taskItem',
            attrs: { checked },
            content: inlineContent.length > 0
              ? [{ type: 'paragraph', content: inlineContent }]
              : [{ type: 'paragraph' }],
          });
        } else {
          const text = rawText.trim();
          // Always create list items (even empty ones)
          const inlineContent = parseInlineMarkdown(text);
          items.push({
            type: 'listItem',
            content: inlineContent.length > 0
              ? [{ type: 'paragraph', content: inlineContent }]
              : [{ type: 'paragraph' }],
          });
        }
        i++;
      }
      // Only add list if we have items
      if (items.length > 0) {
        // Check if this was a task list
        if (items[0].type === 'taskItem') {
          content.push({ type: 'taskList', content: items });
        } else {
          content.push({ type: 'bulletList', content: items });
        }
      }
      continue;
    }

    // Numbered list
    if (/^\d+\. /.test(line)) {
      const items: Array<Record<string, unknown>> = [];
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        const text = lines[i].replace(/^\d+\. /, '').trim();
        // Always create list items (even empty ones)
        const inlineContent = parseInlineMarkdown(text);
        items.push({
          type: 'listItem',
          content: inlineContent.length > 0
            ? [{ type: 'paragraph', content: inlineContent }]
            : [{ type: 'paragraph' }],
        });
        i++;
      }
      // Only add list if we have items
      if (items.length > 0) {
        content.push({ type: 'orderedList', content: items });
      }
      continue;
    }

    // Code block
    if (line.startsWith('```')) {
      const lang = line.slice(3).trim();
      const codeLines: string[] = [];
      i++;
      while (i < lines.length && !lines[i].startsWith('```')) {
        codeLines.push(lines[i]);
        i++;
      }
      i++; // Skip closing ```
      content.push({
        type: 'codeBlock',
        attrs: { language: lang || 'text' },
        content: codeLines.length > 0 ? [{ type: 'text', text: codeLines.join('\n') }] : undefined,
      });
      continue;
    }

    // Blockquote
    if (line.startsWith('> ')) {
      const text = line.slice(2).trim();
      // Always create blockquote (even with empty paragraph inside)
      const inlineContent = parseInlineMarkdown(text);
      content.push({
        type: 'blockquote',
        content: inlineContent.length > 0
          ? [{ type: 'paragraph', content: inlineContent }]
          : [{ type: 'paragraph' }],
      });
      i++;
      continue;
    }

    // Table (starts with |)
    if (line.trim().startsWith('|') && line.trim().endsWith('|')) {
      const tableRows: string[][] = [];
      let hasHeaderSeparator = false;

      // Collect all table lines
      while (i < lines.length) {
        const tableLine = lines[i].trim();
        if (!tableLine.startsWith('|') || !tableLine.endsWith('|')) {
          break;
        }

        // Parse cells from line (remove leading/trailing |, split by |)
        const cells = tableLine.slice(1, -1).split('|').map(c => c.trim());

        // Check if this is the separator row (e.g., |---|---|)
        if (cells.every(c => /^[-:]+$/.test(c))) {
          hasHeaderSeparator = true;
          i++;
          continue;
        }

        tableRows.push(cells);
        i++;
      }

      if (tableRows.length > 0) {
        // Convert to TipTap table format
        const headerRow = tableRows[0];
        const dataRows = tableRows.slice(1);

        const tiptapRows: Array<Record<string, unknown>> = [];

        // Header row
        tiptapRows.push({
          type: 'tableRow',
          content: headerRow.map(cellText => {
            const inlineContent = parseInlineMarkdown(cellText);
            return {
              type: 'tableHeader',
              attrs: { colspan: 1, rowspan: 1 },
              content: [{ type: 'paragraph', content: inlineContent.length > 0 ? inlineContent : [] }],
            };
          }),
        });

        // Data rows
        for (const row of dataRows) {
          tiptapRows.push({
            type: 'tableRow',
            content: row.map(cellText => {
              const inlineContent = parseInlineMarkdown(cellText);
              return {
                type: 'tableCell',
                attrs: { colspan: 1, rowspan: 1 },
                content: [{ type: 'paragraph', content: inlineContent.length > 0 ? inlineContent : [] }],
              };
            }),
          });
        }

        content.push({ type: 'table', content: tiptapRows });
      }
      continue;
    }

    // Default: paragraph - parse inline markdown formatting
    const trimmedLine = line.trim();
    if (trimmedLine) {
      const inlineContent = parseInlineMarkdown(trimmedLine);
      if (inlineContent.length > 0) {
        content.push({
          type: 'paragraph',
          content: inlineContent,
        });
      }
    }
    // Skip lines that are only whitespace (shouldn't reach here due to earlier check, but be safe)
    i++;
  }

  // Ensure we always return valid content - at least one paragraph
  if (content.length === 0) {
    return {
      type: 'doc',
      content: [{ type: 'paragraph' }],
    };
  }

  return {
    type: 'doc',
    content,
  };
}

export default BlockEditor;
