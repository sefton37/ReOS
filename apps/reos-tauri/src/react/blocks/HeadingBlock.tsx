/**
 * HeadingBlock - Renders heading blocks (h1, h2, h3).
 */

import type { Block } from '../types';
import { RichTextContent } from './RichTextContent';

interface HeadingBlockProps {
  block: Block;
  onUpdate?: (block: Block) => void;
  onDelete?: (blockId: string) => void;
  isEditing?: boolean;
  depth?: number;
}

export function HeadingBlock({
  block,
  onUpdate,
  isEditing = false,
}: HeadingBlockProps) {
  const level = block.type === 'heading_1' ? 1 : block.type === 'heading_2' ? 2 : 3;

  const styles: Record<number, React.CSSProperties> = {
    1: {
      fontSize: '1.75em',
      fontWeight: 700,
      margin: '1em 0 0.5em 0',
      color: '#f3f4f6',
      lineHeight: 1.3,
    },
    2: {
      fontSize: '1.5em',
      fontWeight: 600,
      margin: '0.8em 0 0.4em 0',
      color: '#f3f4f6',
      lineHeight: 1.3,
    },
    3: {
      fontSize: '1.25em',
      fontWeight: 600,
      margin: '0.6em 0 0.3em 0',
      color: '#f3f4f6',
      lineHeight: 1.3,
    },
  };

  const Tag = `h${level}` as 'h1' | 'h2' | 'h3';

  return (
    <Tag style={styles[level]}>
      <RichTextContent spans={block.rich_text} />
    </Tag>
  );
}

export default HeadingBlock;
