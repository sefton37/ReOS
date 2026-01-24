/**
 * PageLinkExtension - TipTap extension for [[ page link autocomplete.
 * Triggers on "[[" and shows a page search autocomplete.
 */

import { Extension } from '@tiptap/core';
import Suggestion, { SuggestionOptions } from '@tiptap/suggestion';

export interface PageLinkOptions {
  suggestion: Partial<SuggestionOptions>;
}

export const PageLinkExtension = Extension.create<PageLinkOptions>({
  name: 'pageLink',

  addOptions() {
    return {
      suggestion: {
        char: '[[',
        startOfLine: false,
        command: ({ editor, range, props }) => {
          // Delete the "[[" and any query text
          editor.chain().focus().deleteRange(range).run();

          // Insert the page link
          if (props?.pageId && props?.title) {
            editor
              .chain()
              .focus()
              .insertContent({
                type: 'text',
                marks: [
                  {
                    type: 'link',
                    attrs: {
                      href: `page://${props.pageId}`,
                      class: 'page-link',
                    },
                  },
                ],
                text: props.title,
              })
              .run();
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

export default PageLinkExtension;
