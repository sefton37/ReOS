/**
 * DocumentNode - TipTap Node extension for document blocks.
 *
 * Renders as an atomic, non-editable block showing document info.
 * Used for documents inserted via /document slash command.
 */

import { Node, mergeAttributes } from '@tiptap/core';
import { ReactNodeViewRenderer } from '@tiptap/react';
import { DocumentCard } from '../components/DocumentCard';

export interface DocumentNodeAttributes {
  documentId: string;
  fileName: string;
  fileType: string;
  fileSize: number;
  chunkCount: number;
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    documentBlock: {
      /**
       * Insert a document block
       */
      insertDocumentBlock: (attrs: DocumentNodeAttributes) => ReturnType;
    };
  }
}

export const DocumentNode = Node.create({
  name: 'documentBlock',

  group: 'block',

  // Atomic = cannot be split or have cursor inside
  atom: true,

  // Can be dragged around
  draggable: true,

  // Not selectable as text
  selectable: true,

  addAttributes() {
    return {
      documentId: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-document-id'),
        renderHTML: (attributes) => ({
          'data-document-id': attributes.documentId,
        }),
      },
      fileName: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-file-name'),
        renderHTML: (attributes) => ({
          'data-file-name': attributes.fileName,
        }),
      },
      fileType: {
        default: '',
        parseHTML: (element) => element.getAttribute('data-file-type'),
        renderHTML: (attributes) => ({
          'data-file-type': attributes.fileType,
        }),
      },
      fileSize: {
        default: 0,
        parseHTML: (element) => parseInt(element.getAttribute('data-file-size') || '0', 10),
        renderHTML: (attributes) => ({
          'data-file-size': attributes.fileSize,
        }),
      },
      chunkCount: {
        default: 0,
        parseHTML: (element) => parseInt(element.getAttribute('data-chunk-count') || '0', 10),
        renderHTML: (attributes) => ({
          'data-chunk-count': attributes.chunkCount,
        }),
      },
    };
  },

  parseHTML() {
    return [
      {
        tag: 'div[data-type="document-block"]',
      },
    ];
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(HTMLAttributes, { 'data-type': 'document-block' }),
    ];
  },

  addNodeView() {
    return ReactNodeViewRenderer(DocumentCard);
  },

  addCommands() {
    return {
      insertDocumentBlock:
        (attrs: DocumentNodeAttributes) =>
        ({ commands }) => {
          return commands.insertContent({
            type: this.name,
            attrs,
          });
        },
    };
  },
});

export default DocumentNode;
