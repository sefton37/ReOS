/**
 * DividerBlock - Renders a horizontal divider line.
 */

import type { Block } from '../types';

interface DividerBlockProps {
  block: Block;
  onUpdate?: (block: Block) => void;
  onDelete?: (blockId: string) => void;
  isEditing?: boolean;
  depth?: number;
}

export function DividerBlock({
  block,
  onUpdate,
  isEditing = false,
}: DividerBlockProps) {
  return (
    <hr
      style={{
        border: 'none',
        borderTop: '1px solid rgba(255, 255, 255, 0.15)',
        margin: '1em 0',
      }}
    />
  );
}

export default DividerBlock;
