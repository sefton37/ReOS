/**
 * ParagraphBlock - Renders a paragraph block with rich text content.
 */

import type { Block } from '../types';
import { RichTextContent } from './RichTextContent';

interface ParagraphBlockProps {
  block: Block;
  onUpdate?: (block: Block) => void;
  onDelete?: (blockId: string) => void;
  isEditing?: boolean;
  depth?: number;
}

export function ParagraphBlock({
  block,
  onUpdate,
  isEditing = false,
}: ParagraphBlockProps) {
  return (
    <p
      style={{
        margin: '0 0 0.5em 0',
        color: '#e5e7eb',
        fontSize: '14px',
        lineHeight: 1.7,
      }}
    >
      <RichTextContent spans={block.rich_text} />
    </p>
  );
}

export default ParagraphBlock;
