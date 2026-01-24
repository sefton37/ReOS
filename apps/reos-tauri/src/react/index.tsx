/**
 * React entry point for the block editor.
 * Provides mount/unmount functions for integration with vanilla TypeScript shell.
 */

import { createRoot, Root } from 'react-dom/client';
import { StrictMode } from 'react';
import BlockEditor from './BlockEditor';
import type { BlockEditorProps } from './types';

// Store active React roots for cleanup
const activeRoots = new Map<HTMLElement, Root>();

/**
 * Mount the BlockEditor React component into a DOM element.
 *
 * @param container - The DOM element to mount into
 * @param props - Props for the BlockEditor component
 * @returns Cleanup function to unmount the component
 */
export function mountBlockEditor(
  container: HTMLElement,
  props: BlockEditorProps,
): () => void {
  // Clean up any existing root
  const existingRoot = activeRoots.get(container);
  if (existingRoot) {
    existingRoot.unmount();
    activeRoots.delete(container);
  }

  // Create new React root
  const root = createRoot(container);
  activeRoots.set(container, root);

  // Render the BlockEditor
  root.render(
    <StrictMode>
      <BlockEditor {...props} />
    </StrictMode>,
  );

  // Return cleanup function
  return () => {
    const currentRoot = activeRoots.get(container);
    if (currentRoot) {
      currentRoot.unmount();
      activeRoots.delete(container);
    }
  };
}

/**
 * Update props for an already mounted BlockEditor.
 *
 * @param container - The DOM element containing the mounted editor
 * @param props - New props for the BlockEditor
 */
export function updateBlockEditor(
  container: HTMLElement,
  props: BlockEditorProps,
): void {
  const root = activeRoots.get(container);
  if (root) {
    root.render(
      <StrictMode>
        <BlockEditor {...props} />
      </StrictMode>,
    );
  }
}

/**
 * Unmount the BlockEditor from a container.
 *
 * @param container - The DOM element to unmount from
 */
export function unmountBlockEditor(container: HTMLElement): void {
  const root = activeRoots.get(container);
  if (root) {
    root.unmount();
    activeRoots.delete(container);
  }
}

// Re-export types for convenience
export type { BlockEditorProps } from './types';
export { BlockEditor };
