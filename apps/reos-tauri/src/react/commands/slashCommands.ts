/**
 * Slash command definitions for the block editor.
 */

import type { Editor } from '@tiptap/react';

export interface SlashCommand {
  id: string;
  label: string;
  description: string;
  icon: string;
  keywords: string[];
  action: (editor: Editor) => void;
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
