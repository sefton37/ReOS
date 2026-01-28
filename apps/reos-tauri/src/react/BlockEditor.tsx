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
    const block = nodeToBlock(node, actId, pageId, null, position);
    if (block) {
      blocks.push(block);
      position++;
    }
  }

  return blocks;
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
      blockType = 'bulleted_list';
      break;
    case 'orderedList':
      blockType = 'numbered_list';
      break;
    case 'taskList':
      blockType = 'to_do';
      break;
    case 'taskItem':
      blockType = 'to_do';
      properties.checked = nodeAttrs.checked ?? false;
      break;
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
    case 'listItem':
      // List items are handled by their parent
      return null;
    default:
      // Skip unknown node types
      return null;
  }

  const blockId = crypto.randomUUID();

  // Extract text content into rich text spans
  if (nodeContent) {
    let spanPosition = 0;
    for (const child of nodeContent) {
      if (child.type === 'text') {
        const text = child.text as string;
        const marks = (child.marks || []) as Array<{ type: string; attrs?: Record<string, unknown> }>;

        const span: RichTextSpan = {
          id: crypto.randomUUID(),
          block_id: blockId,
          position: spanPosition,
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
        spanPosition++;
      }
    }
  }

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
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saving' | 'saved' | 'error'>('idle');
  const [initialContent, setInitialContent] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const isInitialLoad = useRef(true);

  // Context for slash commands that need kernel access
  const slashCommandContextRef = useRef<SlashCommandContext>({
    kernelRequest,
    actId,
  });

  // Keep context ref up to date
  useEffect(() => {
    slashCommandContextRef.current = { kernelRequest, actId };
  }, [kernelRequest, actId]);

  // Load blocks from backend
  useEffect(() => {
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
          const result = (await kernelRequest('play/kb/read', {
            act_id: actId,
            path: 'kb.md',
          })) as { text: string };

          const markdown = result.text || '';
          const content = markdownToTiptap(markdown);
          setInitialContent(content);
        } catch {
          // Fail gracefully - just show empty editor
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
    isInitialLoad.current = true;

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

    return () => clearTimeout(timeout);
  }, [actId, pageId, kernelRequest]);

  // Save blocks to backend
  const saveBlocks = useCallback(
    async (json: Record<string, unknown>) => {
      if (!actId || isInitialLoad.current) {
        return;
      }

      setSaveStatus('saving');
      onSaveStatusChange?.(true);

      try {
        const blocks = tiptapToBlocks(json, actId, pageId);

        // Save as markdown for now (simpler integration with existing system)
        const markdown = blocksToMarkdown(blocks);

        if (pageId) {
          await kernelRequest('play/pages/content/write', {
            act_id: actId,
            page_id: pageId,
            text: markdown,
          });
        } else {
          // Save to act-level KB
          const preview = await kernelRequest('play/kb/write_preview', {
            act_id: actId,
            path: 'kb.md',
            text: markdown,
          }) as { expected_sha256_current: string };

          await kernelRequest('play/kb/write_apply', {
            act_id: actId,
            path: 'kb.md',
            text: markdown,
            expected_sha256_current: preview.expected_sha256_current,
          });
        }

        setSaveStatus('saved');
        onSaveStatusChange?.(false);

        // Reset to idle after a short delay
        setTimeout(() => setSaveStatus('idle'), 2000);
      } catch (e) {
        console.error('Failed to save blocks:', e);
        setSaveStatus('error');
        onSaveStatusChange?.(false);
      }
    },
    [actId, pageId, kernelRequest, onSaveStatusChange],
  );

  // Debounced save with flush-on-unmount to prevent data loss
  const debouncedSave = useDebounce(saveBlocks, 500, true);

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
        if (isInitialLoad.current) {
          isInitialLoad.current = false;
          return;
        }
        const json = editor.getJSON();
        debouncedSave(json);
      },
      onBlur: ({ editor }) => {
        // Save immediately when editor loses focus (user clicked away)
        if (!isInitialLoad.current) {
          const json = editor.getJSON();
          void saveBlocks(json);
        }
      },
      editorProps: {
        attributes: {
          class: 'ProseMirror',
        },
      },
    },
    [initialContent],
  );

  // Update content when initialContent changes
  useEffect(() => {
    if (editor && initialContent) {
      editor.commands.setContent(initialContent);
      isInitialLoad.current = true;
    }
  }, [editor, initialContent]);

  // Save immediately on window close (beforeunload) to prevent data loss
  useEffect(() => {
    if (!editor || !actId) return;

    const handleBeforeUnload = () => {
      // Save synchronously-ish by firing the save (can't truly await in beforeunload)
      // The flush-on-unmount in useDebounce handles most cases, but this is a safety net
      const json = editor.getJSON();
      if (json && !isInitialLoad.current) {
        // Fire and forget - we can't await here
        void saveBlocks(json);
      }
    };

    // Also save when page becomes hidden (tab switch, minimize, etc.)
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        const json = editor.getJSON();
        if (json && !isInitialLoad.current) {
          void saveBlocks(json);
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

  for (const block of blocks) {
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
 * Parse simple markdown into TipTap JSON format.
 */
function markdownToTiptap(markdown: string): Record<string, unknown> {
  const lines = markdown.split('\n');
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
      content.push({
        type: 'heading',
        attrs: { level: 1 },
        content: [{ type: 'text', text: line.slice(2) }],
      });
      i++;
      continue;
    }

    // Heading 2
    if (line.startsWith('## ')) {
      content.push({
        type: 'heading',
        attrs: { level: 2 },
        content: [{ type: 'text', text: line.slice(3) }],
      });
      i++;
      continue;
    }

    // Heading 3
    if (line.startsWith('### ')) {
      content.push({
        type: 'heading',
        attrs: { level: 3 },
        content: [{ type: 'text', text: line.slice(4) }],
      });
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
        const text = lines[i].slice(2);
        // Check for todo
        if (text.startsWith('[ ] ') || text.startsWith('[x] ')) {
          const checked = text.startsWith('[x]');
          items.push({
            type: 'taskItem',
            attrs: { checked },
            content: [{ type: 'paragraph', content: [{ type: 'text', text: text.slice(4) }] }],
          });
        } else {
          items.push({
            type: 'listItem',
            content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
          });
        }
        i++;
      }
      // Check if this was a task list
      if (items.length > 0 && items[0].type === 'taskItem') {
        content.push({ type: 'taskList', content: items });
      } else {
        content.push({ type: 'bulletList', content: items });
      }
      continue;
    }

    // Numbered list
    if (/^\d+\. /.test(line)) {
      const items: Array<Record<string, unknown>> = [];
      while (i < lines.length && /^\d+\. /.test(lines[i])) {
        const text = lines[i].replace(/^\d+\. /, '');
        items.push({
          type: 'listItem',
          content: [{ type: 'paragraph', content: [{ type: 'text', text }] }],
        });
        i++;
      }
      content.push({ type: 'orderedList', content: items });
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
      content.push({
        type: 'blockquote',
        content: [{ type: 'paragraph', content: [{ type: 'text', text: line.slice(2) }] }],
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
          content: headerRow.map(cellText => ({
            type: 'tableHeader',
            attrs: { colspan: 1, rowspan: 1 },
            content: [{ type: 'paragraph', content: cellText ? [{ type: 'text', text: cellText }] : [] }],
          })),
        });

        // Data rows
        for (const row of dataRows) {
          tiptapRows.push({
            type: 'tableRow',
            content: row.map(cellText => ({
              type: 'tableCell',
              attrs: { colspan: 1, rowspan: 1 },
              content: [{ type: 'paragraph', content: cellText ? [{ type: 'text', text: cellText }] : [] }],
            })),
          });
        }

        content.push({ type: 'table', content: tiptapRows });
      }
      continue;
    }

    // Default: paragraph
    content.push({
      type: 'paragraph',
      content: line.trim() ? [{ type: 'text', text: line }] : undefined,
    });
    i++;
  }

  return {
    type: 'doc',
    content: content.length > 0 ? content : [{ type: 'paragraph' }],
  };
}

export default BlockEditor;
