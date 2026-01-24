/**
 * useDragDrop - Hook for managing drag and drop state for blocks.
 */

import { useState, useCallback } from 'react';

export interface DragState {
  isDragging: boolean;
  draggedBlockId: string | null;
  dropTargetId: string | null;
  dropPosition: 'before' | 'after' | 'inside' | null;
}

interface UseDragDropOptions {
  onMove: (blockId: string, newParentId: string | null, newPosition: number) => Promise<boolean>;
  onReorder: (parentId: string | null, blockIds: string[]) => Promise<boolean>;
}

interface UseDragDropResult {
  dragState: DragState;
  startDrag: (blockId: string) => void;
  endDrag: () => void;
  setDropTarget: (targetId: string | null, position: 'before' | 'after' | 'inside' | null) => void;
  handleDrop: (targetId: string, position: 'before' | 'after' | 'inside') => Promise<void>;
}

export function useDragDrop(options: UseDragDropOptions): UseDragDropResult {
  const { onMove, onReorder } = options;

  const [dragState, setDragState] = useState<DragState>({
    isDragging: false,
    draggedBlockId: null,
    dropTargetId: null,
    dropPosition: null,
  });

  const startDrag = useCallback((blockId: string) => {
    setDragState({
      isDragging: true,
      draggedBlockId: blockId,
      dropTargetId: null,
      dropPosition: null,
    });
  }, []);

  const endDrag = useCallback(() => {
    setDragState({
      isDragging: false,
      draggedBlockId: null,
      dropTargetId: null,
      dropPosition: null,
    });
  }, []);

  const setDropTarget = useCallback(
    (targetId: string | null, position: 'before' | 'after' | 'inside' | null) => {
      setDragState((prev) => ({
        ...prev,
        dropTargetId: targetId,
        dropPosition: position,
      }));
    },
    [],
  );

  const handleDrop = useCallback(
    async (targetId: string, position: 'before' | 'after' | 'inside') => {
      const { draggedBlockId } = dragState;

      if (!draggedBlockId || draggedBlockId === targetId) {
        endDrag();
        return;
      }

      try {
        if (position === 'inside') {
          // Move block inside another block (make it a child)
          await onMove(draggedBlockId, targetId, 0);
        } else {
          // Move block before or after another block at the same level
          // This requires knowing the target's position and parent
          // For now, we'll use a simplified approach
          const newPosition = position === 'before' ? 0 : 1;
          await onMove(draggedBlockId, null, newPosition);
        }
      } catch (error) {
        console.error('Failed to move block:', error);
      } finally {
        endDrag();
      }
    },
    [dragState, onMove, endDrag],
  );

  return {
    dragState,
    startDrag,
    endDrag,
    setDropTarget,
    handleDrop,
  };
}

export default useDragDrop;
