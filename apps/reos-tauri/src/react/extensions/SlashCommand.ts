/**
 * SlashCommand - TipTap extension for slash command menu.
 * Triggers on "/" and shows a command palette.
 */

import { Extension } from '@tiptap/core';
import Suggestion, { SuggestionOptions } from '@tiptap/suggestion';
import type { Editor } from '@tiptap/react';

export interface SlashCommandOptions {
  suggestion: Partial<SuggestionOptions>;
}

export const SlashCommand = Extension.create<SlashCommandOptions>({
  name: 'slashCommand',

  addOptions() {
    return {
      suggestion: {
        char: '/',
        startOfLine: false,
        command: ({ editor, range, props }) => {
          // Delete the "/" and any query text
          editor.chain().focus().deleteRange(range).run();
          // Execute the command
          if (props?.action) {
            props.action(editor);
          }
        },
      },
    };
  },

  addProseMirrorPlugins() {
    return [
      Suggestion({
        editor: this.editor,
        ...this.options.suggestion,
      }),
    ];
  },
});

export default SlashCommand;
