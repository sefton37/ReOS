import { useState, useCallback, useEffect } from 'react';
import type {
  Block,
  BlockType,
  RichTextSpan,
  BlocksPageTreeResult,
  BlockCreateResult,
  BlockUpdateResult,
} from '../types';

interface UseBlocksOptions {
  actId: string;
  pageId: string | null;
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
}

interface UseBlocksResult {
  blocks: Block[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  createBlock: (
    type: BlockType,
    parentId?: string | null,
    position?: number,
    content?: string,
  ) => Promise<Block | null>;
  updateBlock: (blockId: string, updates: Partial<Block>) => Promise<Block | null>;
  deleteBlock: (blockId: string) => Promise<boolean>;
  moveBlock: (blockId: string, newParentId: string | null, newPosition: number) => Promise<boolean>;
  reorderBlocks: (parentId: string | null, blockIds: string[]) => Promise<boolean>;
  updateRichText: (blockId: string, spans: RichTextSpan[]) => Promise<boolean>;
  setProperty: (blockId: string, key: string, value: unknown) => Promise<boolean>;
}

/**
 * Hook for managing blocks within a page/act.
 * Provides CRUD operations via RPC calls to the backend.
 */
export function useBlocks(options: UseBlocksOptions): UseBlocksResult {
  const { actId, pageId, kernelRequest } = options;

  const [blocks, setBlocks] = useState<Block[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Load blocks for the current page
  const reload = useCallback(async () => {
    if (!actId) {
      setBlocks([]);
      setLoading(false);
      return;
    }

    setLoading(true);
    setError(null);

    try {
      const result = (await kernelRequest('blocks/page/tree', {
        act_id: actId,
        page_id: pageId,
      })) as BlocksPageTreeResult;

      setBlocks(result.blocks ?? []);
    } catch (e) {
      console.error('Failed to load blocks:', e);
      setError(e instanceof Error ? e.message : 'Failed to load blocks');
      setBlocks([]);
    } finally {
      setLoading(false);
    }
  }, [actId, pageId, kernelRequest]);

  // Load on mount and when actId/pageId changes
  useEffect(() => {
    void reload();
  }, [reload]);

  // Create a new block
  const createBlock = useCallback(
    async (
      type: BlockType,
      parentId: string | null = null,
      position: number = 0,
      content: string = '',
    ): Promise<Block | null> => {
      try {
        const result = (await kernelRequest('blocks/create', {
          act_id: actId,
          type,
          parent_id: parentId,
          page_id: pageId,
          position,
          content,
        })) as BlockCreateResult;

        // Optimistically add to local state
        setBlocks((prev) => [...prev, result.block]);

        return result.block;
      } catch (e) {
        console.error('Failed to create block:', e);
        return null;
      }
    },
    [actId, pageId, kernelRequest],
  );

  // Update a block
  const updateBlock = useCallback(
    async (blockId: string, updates: Partial<Block>): Promise<Block | null> => {
      try {
        const result = (await kernelRequest('blocks/update', {
          block_id: blockId,
          ...updates,
        })) as BlockUpdateResult;

        // Update local state
        setBlocks((prev) =>
          prev.map((b) => (b.id === blockId ? { ...b, ...result.block } : b)),
        );

        return result.block;
      } catch (e) {
        console.error('Failed to update block:', e);
        return null;
      }
    },
    [kernelRequest],
  );

  // Delete a block
  const deleteBlock = useCallback(
    async (blockId: string): Promise<boolean> => {
      try {
        await kernelRequest('blocks/delete', { block_id: blockId });

        // Remove from local state
        setBlocks((prev) => prev.filter((b) => b.id !== blockId));

        return true;
      } catch (e) {
        console.error('Failed to delete block:', e);
        return false;
      }
    },
    [kernelRequest],
  );

  // Move a block to a new parent/position
  const moveBlock = useCallback(
    async (
      blockId: string,
      newParentId: string | null,
      newPosition: number,
    ): Promise<boolean> => {
      try {
        await kernelRequest('blocks/move', {
          block_id: blockId,
          new_parent_id: newParentId,
          new_position: newPosition,
        });

        // Reload to get updated positions
        await reload();

        return true;
      } catch (e) {
        console.error('Failed to move block:', e);
        return false;
      }
    },
    [kernelRequest, reload],
  );

  // Reorder blocks within a parent
  const reorderBlocks = useCallback(
    async (parentId: string | null, blockIds: string[]): Promise<boolean> => {
      try {
        await kernelRequest('blocks/reorder', {
          parent_id: parentId,
          block_ids: blockIds,
        });

        // Reload to get updated positions
        await reload();

        return true;
      } catch (e) {
        console.error('Failed to reorder blocks:', e);
        return false;
      }
    },
    [kernelRequest, reload],
  );

  // Update rich text spans for a block
  const updateRichText = useCallback(
    async (blockId: string, spans: RichTextSpan[]): Promise<boolean> => {
      try {
        await kernelRequest('blocks/rich_text/set', {
          block_id: blockId,
          spans: spans.map((s) => ({
            ...s,
            block_id: blockId,
          })),
        });

        // Update local state
        setBlocks((prev) =>
          prev.map((b) =>
            b.id === blockId ? { ...b, rich_text: spans } : b,
          ),
        );

        return true;
      } catch (e) {
        console.error('Failed to update rich text:', e);
        return false;
      }
    },
    [kernelRequest],
  );

  // Set a property on a block
  const setProperty = useCallback(
    async (blockId: string, key: string, value: unknown): Promise<boolean> => {
      try {
        await kernelRequest('blocks/property/set', {
          block_id: blockId,
          key,
          value,
        });

        // Update local state
        setBlocks((prev) =>
          prev.map((b) =>
            b.id === blockId
              ? { ...b, properties: { ...b.properties, [key]: value } }
              : b,
          ),
        );

        return true;
      } catch (e) {
        console.error('Failed to set property:', e);
        return false;
      }
    },
    [kernelRequest],
  );

  return {
    blocks,
    loading,
    error,
    reload,
    createBlock,
    updateBlock,
    deleteBlock,
    moveBlock,
    reorderBlocks,
    updateRichText,
    setProperty,
  };
}
