/**
 * Play Act View - Notion-style block editor with nested pages
 *
 * Left sidebar shows Acts with nested pages (collapsible page tree).
 * Right content area shows TipTap block editor for selected Act/Page.
 */

import { el } from './dom';
import type {
  PlayActsListResult,
  PlayPageTreeNode,
} from './types';
import { mountBlockEditor } from './react';

// Color palette for Acts (matches Python ACT_COLOR_PALETTE)
const ACT_COLOR_PALETTE = [
  '#8b5cf6',  // Purple (violet-500)
  '#3b82f6',  // Blue (blue-500)
  '#10b981',  // Green (emerald-500)
  '#f59e0b',  // Amber (amber-500)
  '#ef4444',  // Red (red-500)
  '#ec4899',  // Pink (pink-500)
  '#06b6d4',  // Cyan (cyan-500)
  '#84cc16',  // Lime (lime-500)
  '#f97316',  // Orange (orange-500)
  '#6366f1',  // Indigo (indigo-500)
  '#14b8a6',  // Teal (teal-500)
  '#a855f7',  // Fuchsia (purple-500)
];

interface PlayActViewState {
  actsCache: PlayActsListResult['acts'];
  activeActId: string | null;
  pagesCache: Map<string, PlayPageTreeNode[]>;  // act_id -> pages
  selectedPageId: string | null;
  expandedActs: Set<string>;
  expandedPages: Set<string>;
  editorCleanup: (() => void) | null;
  editorContainer: HTMLElement | null;
}

interface PlayActViewOptions {
  onActsChange: () => Promise<void>;
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
}

export function createPlayActView(options: PlayActViewOptions): {
  element: HTMLElement;
  refresh: () => void;
} {
  const { onActsChange, kernelRequest } = options;

  const state: PlayActViewState = {
    actsCache: [],
    activeActId: null,
    pagesCache: new Map(),
    selectedPageId: null,
    expandedActs: new Set(),
    expandedPages: new Set(),
    editorCleanup: null,
    editorContainer: null,
  };

  // Main container
  const container = el('div');
  container.className = 'play-act-view';
  container.style.cssText = `
    display: flex;
    flex: 1;
    overflow: hidden;
  `;

  // Left sidebar
  const sidebar = el('div');
  sidebar.className = 'play-act-sidebar';
  sidebar.style.cssText = `
    width: 280px;
    min-width: 280px;
    border-right: 1px solid rgba(255, 255, 255, 0.1);
    overflow-y: auto;
    padding: 16px;
    background: rgba(0, 0, 0, 0.15);
  `;

  // Content area
  const content = el('div');
  content.className = 'play-act-content';
  content.style.cssText = `
    flex: 1;
    display: flex;
    flex-direction: column;
    padding: 24px;
    overflow: hidden;
  `;

  container.appendChild(sidebar);
  container.appendChild(content);

  // --- Data Loading ---

  async function loadActs() {
    try {
      console.log(`[PlayActView] ========== LOADING ACTS ==========`);
      const result = await kernelRequest('play/acts/list', {}) as PlayActsListResult;
      console.log(`[PlayActView] Server returned active_act_id: "${result.active_act_id}"`);
      console.log(`[PlayActView] Server returned ${result.acts?.length ?? 0} acts`);
      state.actsCache = result.acts ?? [];
      state.activeActId = result.active_act_id;
      console.log(`[PlayActView] Set state.activeActId to: "${state.activeActId}"`);

      // Auto-expand active act
      if (state.activeActId) {
        state.expandedActs.add(state.activeActId);
      }
    } catch (e) {
      console.error('[PlayActView] Failed to load acts:', e);
    }
  }

  async function loadPages(actId: string) {
    try {
      const result = await kernelRequest('play/pages/tree', { act_id: actId }) as { pages: PlayPageTreeNode[] };
      state.pagesCache.set(actId, result.pages ?? []);
    } catch {
      // Pages endpoint may not exist yet, use empty array
      state.pagesCache.set(actId, []);
    }
  }

  // --- Rendering ---

  function renderSidebar() {
    sidebar.innerHTML = '';

    // "The Play" root (me.md)
    const playItem = el('div');
    playItem.className = 'tree-item play';
    playItem.style.cssText = `
      padding: 8px 12px;
      border-radius: 8px;
      cursor: pointer;
      color: rgba(255, 255, 255, 0.8);
      font-size: 13px;
      transition: background 0.15s;
      display: flex;
      align-items: center;
      gap: 8px;
      margin-bottom: 8px;
      ${!state.activeActId && !state.selectedPageId ? 'background: rgba(34, 197, 94, 0.2); color: #22c55e;' : ''}
    `;
    playItem.innerHTML = '<span style="font-size: 14px;">📘</span> The Play';
    playItem.addEventListener('click', () => selectPlay());
    playItem.addEventListener('mouseenter', () => {
      if (state.activeActId || state.selectedPageId) {
        playItem.style.background = 'rgba(255, 255, 255, 0.08)';
      }
    });
    playItem.addEventListener('mouseleave', () => {
      if (state.activeActId || state.selectedPageId) {
        playItem.style.background = 'transparent';
      }
    });
    sidebar.appendChild(playItem);

    // New Act button
    const newActBtn = el('button');
    newActBtn.className = 'tree-new-btn';
    newActBtn.textContent = '+ New Act';
    newActBtn.style.cssText = `
      width: 100%;
      padding: 6px 12px;
      margin-bottom: 12px;
      border-radius: 6px;
      border: 1px dashed rgba(255, 255, 255, 0.2);
      background: transparent;
      color: rgba(255, 255, 255, 0.5);
      cursor: pointer;
      font-size: 12px;
      text-align: left;
      transition: all 0.15s;
    `;
    newActBtn.addEventListener('click', () => createNewAct());
    newActBtn.addEventListener('mouseenter', () => {
      newActBtn.style.borderColor = 'rgba(34, 197, 94, 0.4)';
      newActBtn.style.color = '#22c55e';
      newActBtn.style.background = 'rgba(34, 197, 94, 0.1)';
    });
    newActBtn.addEventListener('mouseleave', () => {
      newActBtn.style.borderColor = 'rgba(255, 255, 255, 0.2)';
      newActBtn.style.color = 'rgba(255, 255, 255, 0.5)';
      newActBtn.style.background = 'transparent';
    });
    sidebar.appendChild(newActBtn);

    // Acts list
    for (const act of state.actsCache) {
      if (act.act_id === 'your-story') continue;

      const isExpanded = state.expandedActs.has(act.act_id);
      const isSelected = state.activeActId === act.act_id && !state.selectedPageId;
      const actColor = act.color || ACT_COLOR_PALETTE[0];

      const actItem = el('div');
      actItem.className = 'act-tree-item';
      actItem.style.cssText = `
        padding: 8px 12px;
        border-radius: 8px;
        cursor: pointer;
        color: rgba(255, 255, 255, 0.8);
        font-size: 13px;
        transition: background 0.15s;
        display: flex;
        align-items: center;
        gap: 8px;
        margin-bottom: 2px;
        ${isSelected ? 'background: rgba(34, 197, 94, 0.2); color: #22c55e;' : ''}
      `;

      // Expand icon
      const expandIcon = el('span');
      expandIcon.textContent = isExpanded ? '▼' : '▶';
      expandIcon.style.cssText = `
        width: 16px;
        font-size: 10px;
        opacity: 0.6;
        cursor: pointer;
      `;
      expandIcon.addEventListener('click', (e) => {
        e.stopPropagation();
        toggleActExpand(act.act_id);
      });

      // Color indicator
      const colorDot = el('span');
      colorDot.style.cssText = `
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: ${actColor};
        flex-shrink: 0;
      `;

      // Title
      const titleSpan = el('span');
      titleSpan.textContent = act.title;
      titleSpan.style.cssText = `
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
        flex: 1;
      `;

      actItem.appendChild(expandIcon);
      actItem.appendChild(colorDot);
      actItem.appendChild(titleSpan);

      actItem.addEventListener('click', () => selectAct(act.act_id));
      actItem.addEventListener('mouseenter', () => {
        if (!isSelected) actItem.style.background = 'rgba(255, 255, 255, 0.08)';
      });
      actItem.addEventListener('mouseleave', () => {
        if (!isSelected) actItem.style.background = 'transparent';
      });

      sidebar.appendChild(actItem);

      // Pages under this act (if expanded)
      if (isExpanded) {
        const pages = state.pagesCache.get(act.act_id) || [];
        renderPageTree(pages, act.act_id, 1);

        // New page button
        const newPageBtn = el('button');
        newPageBtn.textContent = '+ New Page';
        newPageBtn.style.cssText = `
          width: calc(100% - 24px);
          margin-left: 24px;
          padding: 4px 12px;
          margin-bottom: 8px;
          border-radius: 6px;
          border: 1px dashed rgba(255, 255, 255, 0.15);
          background: transparent;
          color: rgba(255, 255, 255, 0.4);
          cursor: pointer;
          font-size: 11px;
          text-align: left;
          transition: all 0.15s;
        `;
        newPageBtn.addEventListener('click', () => createNewPage(act.act_id));
        newPageBtn.addEventListener('mouseenter', () => {
          newPageBtn.style.borderColor = 'rgba(59, 130, 246, 0.4)';
          newPageBtn.style.color = '#60a5fa';
        });
        newPageBtn.addEventListener('mouseleave', () => {
          newPageBtn.style.borderColor = 'rgba(255, 255, 255, 0.15)';
          newPageBtn.style.color = 'rgba(255, 255, 255, 0.4)';
        });
        sidebar.appendChild(newPageBtn);
      }
    }
  }

  function renderPageTree(pages: PlayPageTreeNode[], actId: string, depth: number) {
    for (const page of pages) {
      const isExpanded = state.expandedPages.has(page.page_id);
      const isSelected = state.selectedPageId === page.page_id;
      const indent = depth * 16;

      const pageItem = el('div');
      pageItem.style.cssText = `
        padding: 6px 12px;
        padding-left: ${12 + indent}px;
        border-radius: 6px;
        cursor: pointer;
        color: rgba(255, 255, 255, 0.7);
        font-size: 12px;
        transition: background 0.15s;
        display: flex;
        align-items: center;
        gap: 6px;
        ${isSelected ? 'background: rgba(59, 130, 246, 0.2); color: #60a5fa;' : ''}
      `;

      // Expand icon (if has children)
      if (page.children && page.children.length > 0) {
        const expandIcon = el('span');
        expandIcon.textContent = isExpanded ? '▼' : '▶';
        expandIcon.style.cssText = `
          width: 12px;
          font-size: 8px;
          opacity: 0.5;
          cursor: pointer;
        `;
        expandIcon.addEventListener('click', (e) => {
          e.stopPropagation();
          togglePageExpand(page.page_id);
        });
        pageItem.appendChild(expandIcon);
      } else {
        const spacer = el('span');
        spacer.style.width = '12px';
        pageItem.appendChild(spacer);
      }

      // Icon
      const icon = el('span');
      icon.textContent = page.icon || '📄';
      icon.style.fontSize = '12px';
      pageItem.appendChild(icon);

      // Title
      const titleSpan = el('span');
      titleSpan.textContent = page.title;
      titleSpan.style.cssText = `
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      `;
      pageItem.appendChild(titleSpan);

      pageItem.addEventListener('click', () => selectPage(actId, page.page_id));
      pageItem.addEventListener('mouseenter', () => {
        if (!isSelected) pageItem.style.background = 'rgba(255, 255, 255, 0.05)';
      });
      pageItem.addEventListener('mouseleave', () => {
        if (!isSelected) pageItem.style.background = 'transparent';
      });

      sidebar.appendChild(pageItem);

      // Render children
      if (isExpanded && page.children && page.children.length > 0) {
        renderPageTree(page.children, actId, depth + 1);
      }
    }
  }

  function renderContent() {
    // Clean up previous React editor if exists
    if (state.editorCleanup) {
      console.log(`[PlayActView] ========== CLEANING UP EDITOR ==========`);
      state.editorCleanup();
      state.editorCleanup = null;
      console.log(`[PlayActView] Editor cleanup complete`);
    }

    content.innerHTML = '';

    // Title
    const titleInput = el('input') as HTMLInputElement;
    titleInput.type = 'text';
    titleInput.placeholder = getContentTitle();
    titleInput.value = getContentTitle();
    titleInput.disabled = !state.activeActId;
    titleInput.style.cssText = `
      font-size: 28px;
      font-weight: 700;
      border: none;
      background: transparent;
      color: #e5e7eb;
      width: 100%;
      padding: 0;
      margin-bottom: 16px;
      outline: none;
    `;
    content.appendChild(titleInput);

    // Editor container for React mount
    const editorWrap = el('div');
    editorWrap.style.cssText = `
      flex: 1;
      display: flex;
      flex-direction: column;
      min-height: 200px;
    `;
    content.appendChild(editorWrap);

    // Mount React BlockEditor
    // Use 'your-story' as the actId when The Play is selected without a specific Act
    // This is the autobiographical entry point for the whole knowledge base
    const editorActId = state.activeActId ?? 'your-story';
    console.log(`[PlayActView] ========== MOUNTING EDITOR ==========`);
    console.log(`[PlayActView] state.activeActId: "${state.activeActId}"`);
    console.log(`[PlayActView] editorActId (after fallback): "${editorActId}"`);
    console.log(`[PlayActView] state.selectedPageId: "${state.selectedPageId}"`);
    state.editorContainer = editorWrap;
    state.editorCleanup = mountBlockEditor(editorWrap, {
      actId: editorActId,
      pageId: state.selectedPageId,
      kernelRequest,
    });
  }

  function getContentTitle(): string {
    if (!state.activeActId) return 'Your Story';
    if (state.selectedPageId) {
      // Find page title from cache
      const pages = state.pagesCache.get(state.activeActId) || [];
      const findPage = (ps: PlayPageTreeNode[]): string => {
        for (const p of ps) {
          if (p.page_id === state.selectedPageId) return p.title;
          if (p.children) {
            const found = findPage(p.children);
            if (found) return found;
          }
        }
        return '';
      };
      return findPage(pages) || 'Page';
    }
    const act = state.actsCache.find(a => a.act_id === state.activeActId);
    return act?.title || 'Act';
  }

  // --- Actions ---

  async function selectPlay() {
    console.log(`[PlayActView] ========== SELECT PLAY ==========`);
    console.log(`[PlayActView] Setting activeActId to null (was: "${state.activeActId}")`);
    state.activeActId = null;
    state.selectedPageId = null;
    await kernelRequest('play/acts/set_active', { act_id: null });
    console.log(`[PlayActView] Calling render()`);
    render();
  }

  async function selectAct(actId: string) {
    state.activeActId = actId;
    state.selectedPageId = null;
    state.expandedActs.add(actId);

    await kernelRequest('play/acts/set_active', { act_id: actId });
    await loadPages(actId);
    render();
  }

  async function selectPage(actId: string, pageId: string) {
    state.activeActId = actId;
    state.selectedPageId = pageId;
    render();
  }

  function toggleActExpand(actId: string) {
    if (state.expandedActs.has(actId)) {
      state.expandedActs.delete(actId);
    } else {
      state.expandedActs.add(actId);
      void loadPages(actId);
    }
    render();
  }

  function togglePageExpand(pageId: string) {
    if (state.expandedPages.has(pageId)) {
      state.expandedPages.delete(pageId);
    } else {
      state.expandedPages.add(pageId);
    }
    render();
  }

  async function createNewAct() {
    const title = prompt('Enter Act title:');
    if (!title?.trim()) return;

    try {
      await kernelRequest('play/acts/create', { title: title.trim() });
      await loadActs();
      await onActsChange();
      render();
    } catch (e) {
      console.error('Failed to create act:', e);
    }
  }

  async function createNewPage(actId: string, parentPageId?: string) {
    const title = prompt('Enter page title:');
    if (!title?.trim()) return;

    try {
      await kernelRequest('play/pages/create', {
        act_id: actId,
        parent_page_id: parentPageId || null,
        title: title.trim(),
      });
      await loadPages(actId);
      render();
    } catch (e) {
      console.error('Failed to create page:', e);
    }
  }

  function render() {
    renderSidebar();
    renderContent();
  }

  async function refresh() {
    await loadActs();
    if (state.activeActId) {
      await loadPages(state.activeActId);
    }
    render();
  }

  // Initial render
  void refresh();

  return {
    element: container,
    refresh,
  };
}
