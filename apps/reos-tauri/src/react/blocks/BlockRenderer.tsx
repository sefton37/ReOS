/**
 * BlockRenderer - Main component that renders blocks based on their type.
 * Switches on block.type to render the appropriate component.
 */

import type { Block } from '../types';
import { ParagraphBlock } from './ParagraphBlock';
import { HeadingBlock } from './HeadingBlock';
import { BulletedListBlock } from './BulletedListBlock';
import { NumberedListBlock } from './NumberedListBlock';
import { TodoBlock } from './TodoBlock';
import { CodeBlock } from './CodeBlock';
import { DividerBlock } from './DividerBlock';
import { CalloutBlock } from './CalloutBlock';
import { SceneBlock } from './SceneBlock';

interface BlockRendererProps {
  block: Block;
  onUpdate?: (block: Block) => void;
  onDelete?: (blockId: string) => void;
  isEditing?: boolean;
  depth?: number;
}

export function BlockRenderer({
  block,
  onUpdate,
  onDelete,
  isEditing = false,
  depth = 0,
}: BlockRendererProps) {
  const commonProps = {
    block,
    onUpdate,
    onDelete,
    isEditing,
    depth,
  };

  switch (block.type) {
    case 'paragraph':
      return <ParagraphBlock {...commonProps} />;

    case 'heading_1':
    case 'heading_2':
    case 'heading_3':
      return <HeadingBlock {...commonProps} />;

    case 'bulleted_list':
      return <BulletedListBlock {...commonProps} />;

    case 'numbered_list':
      return <NumberedListBlock {...commonProps} />;

    case 'to_do':
      return <TodoBlock {...commonProps} />;

    case 'code':
      return <CodeBlock {...commonProps} />;

    case 'divider':
      return <DividerBlock {...commonProps} />;

    case 'callout':
      return <CalloutBlock {...commonProps} />;

    case 'scene':
      return <SceneBlock {...commonProps} />;

    case 'page':
      // Pages are container blocks, render children
      return (
        <div className="page-block">
          {block.children.map((child) => (
            <BlockRenderer
              key={child.id}
              block={child}
              onUpdate={onUpdate}
              onDelete={onDelete}
              isEditing={isEditing}
              depth={depth + 1}
            />
          ))}
        </div>
      );

    default:
      // Fallback for unknown block types
      return (
        <div
          style={{
            padding: '8px 12px',
            background: 'rgba(255, 255, 255, 0.05)',
            borderRadius: '4px',
            color: 'rgba(255, 255, 255, 0.5)',
            fontSize: '12px',
            fontStyle: 'italic',
          }}
        >
          Unknown block type: {block.type}
        </div>
      );
  }
}

export default BlockRenderer;
