/**
 * Slash command definitions for the block editor.
 */

import type { Editor } from '@tiptap/react';

/**
 * Context passed to slash command actions for async operations.
 */
export interface SlashCommandContext {
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  actId: string | null;
}

export interface SlashCommand {
  id: string;
  label: string;
  description: string;
  icon: string;
  keywords: string[];
  /** If true, this command requires context (kernelRequest, actId) */
  requiresContext?: boolean;
  action: (editor: Editor, context?: SlashCommandContext) => void | Promise<void>;
}

/**
 * All available slash commands.
 */
export const slashCommands: SlashCommand[] = [
  // Text blocks
  {
    id: 'paragraph',
    label: 'Text',
    description: 'Plain text paragraph',
    icon: '📝',
    keywords: ['text', 'paragraph', 'p'],
    action: (editor) => {
      editor.chain().focus().setParagraph().run();
    },
  },
  {
    id: 'heading_1',
    label: 'Heading 1',
    description: 'Large section heading',
    icon: 'H1',
    keywords: ['h1', 'heading', 'title', 'large'],
    action: (editor) => {
      editor.chain().focus().toggleHeading({ level: 1 }).run();
    },
  },
  {
    id: 'heading_2',
    label: 'Heading 2',
    description: 'Medium section heading',
    icon: 'H2',
    keywords: ['h2', 'heading', 'subtitle', 'medium'],
    action: (editor) => {
      editor.chain().focus().toggleHeading({ level: 2 }).run();
    },
  },
  {
    id: 'heading_3',
    label: 'Heading 3',
    description: 'Small section heading',
    icon: 'H3',
    keywords: ['h3', 'heading', 'small'],
    action: (editor) => {
      editor.chain().focus().toggleHeading({ level: 3 }).run();
    },
  },

  // List blocks
  {
    id: 'bullet',
    label: 'Bullet List',
    description: 'Unordered list with bullets',
    icon: '•',
    keywords: ['bullet', 'list', 'unordered', 'ul'],
    action: (editor) => {
      editor.chain().focus().toggleBulletList().run();
    },
  },
  {
    id: 'number',
    label: 'Numbered List',
    description: 'Ordered list with numbers',
    icon: '1.',
    keywords: ['number', 'list', 'ordered', 'ol'],
    action: (editor) => {
      editor.chain().focus().toggleOrderedList().run();
    },
  },
  {
    id: 'todo',
    label: 'To-do',
    description: 'Task with checkbox',
    icon: '☑️',
    keywords: ['todo', 'task', 'checkbox', 'check'],
    action: (editor) => {
      editor.chain().focus().toggleTaskList().run();
    },
  },

  // Special blocks
  {
    id: 'code',
    label: 'Code',
    description: 'Code block with syntax highlighting',
    icon: '</>',
    keywords: ['code', 'codeblock', 'programming', 'pre'],
    action: (editor) => {
      editor.chain().focus().toggleCodeBlock().run();
    },
  },
  {
    id: 'divider',
    label: 'Divider',
    description: 'Horizontal line separator',
    icon: '─',
    keywords: ['divider', 'hr', 'horizontal', 'line', 'separator'],
    action: (editor) => {
      editor.chain().focus().setHorizontalRule().run();
    },
  },
  {
    id: 'quote',
    label: 'Quote',
    description: 'Quote or callout block',
    icon: '❝',
    keywords: ['quote', 'blockquote', 'callout'],
    action: (editor) => {
      editor.chain().focus().toggleBlockquote().run();
    },
  },

  // Data blocks
  {
    id: 'table',
    label: 'Table',
    description: 'Data table with rows and columns',
    icon: '⊞',
    keywords: ['table', 'grid', 'data', 'spreadsheet', 'cells'],
    action: (editor) => {
      // Prompt for dimensions
      const rowsInput = prompt('Number of data rows:', '3');
      if (rowsInput === null) return; // User cancelled

      const colsInput = prompt('Number of columns:', '3');
      if (colsInput === null) return; // User cancelled

      const dataRows = Math.max(1, Math.min(20, parseInt(rowsInput, 10) || 3));
      const cols = Math.max(1, Math.min(10, parseInt(colsInput, 10) || 3));

      // Add 1 for header row + requested data rows
      editor.chain().focus().insertTable({ rows: dataRows + 1, cols, withHeaderRow: true }).run();
    },
  },

  // Knowledge base blocks
  {
    id: 'document',
    label: 'Document',
    description: 'Insert document into knowledge base',
    icon: '📄',
    keywords: ['document', 'pdf', 'upload', 'attach', 'file', 'insert', 'docx', 'word', 'excel'],
    requiresContext: true,
    action: async (editor, context) => {
      if (!context) {
        console.warn('Document command requires context');
        return;
      }

      try {
        // Import dialog dynamically to avoid bundling issues
        const { open } = await import('@tauri-apps/plugin-dialog');

        const filePath = await open({
          multiple: false,
          filters: [
            {
              name: 'Documents',
              extensions: ['pdf', 'docx', 'doc', 'txt', 'md', 'csv', 'xlsx', 'xls'],
            },
          ],
          title: 'Select document to add to knowledge base',
        });

        if (!filePath || typeof filePath !== 'string') {
          return; // User cancelled
        }

        // Call backend to process document
        const result = await context.kernelRequest('documents/insert', {
          file_path: filePath,
          act_id: context.actId,
        }) as {
          documentId: string;
          fileName: string;
          fileType: string;
          fileSize: number;
          chunkCount: number;
        };

        // Insert document block into editor
        editor.chain().focus().insertContent({
          type: 'documentBlock',
          attrs: {
            documentId: result.documentId,
            fileName: result.fileName,
            fileType: result.fileType,
            fileSize: result.fileSize,
            chunkCount: result.chunkCount,
          },
        }).run();
      } catch (err) {
        console.error('Failed to insert document:', err);
        // Show error to user
        alert(`Failed to insert document: ${err instanceof Error ? err.message : String(err)}`);
      }
    },
  },
];

/**
 * Filter commands by search query.
 */
export function filterCommands(query: string): SlashCommand[] {
  const lowerQuery = query.toLowerCase().trim();

  if (!lowerQuery) {
    return slashCommands;
  }

  return slashCommands.filter((cmd) => {
    // Match against label
    if (cmd.label.toLowerCase().includes(lowerQuery)) {
      return true;
    }

    // Match against keywords
    return cmd.keywords.some((kw) => kw.includes(lowerQuery));
  });
}

/**
 * Get a command by ID.
 */
export function getCommand(id: string): SlashCommand | undefined {
  return slashCommands.find((cmd) => cmd.id === id);
}
