/**
 * Context menu for table operations.
 * Shows when right-clicking inside a table cell.
 */

import { useEffect, useCallback, useState, useRef } from 'react';
import type { Editor } from '@tiptap/react';
import { Node as ProseMirrorNode } from '@tiptap/pm/model';

interface TableContextMenuProps {
  editor: Editor | null;
}

interface MenuPosition {
  x: number;
  y: number;
}

interface CellInfo {
  isHeader: boolean;
  columnIndex: number;
}

/**
 * Get information about the currently selected cell.
 */
function getSelectedCellInfo(editor: Editor): CellInfo | null {
  const { selection } = editor.state;
  const $pos = selection.$anchor;

  let columnIndex = 0;
  let isHeader = false;

  // Walk up to find cell and row
  for (let depth = $pos.depth; depth > 0; depth--) {
    const node = $pos.node(depth);

    if (node.type.name === 'tableCell' || node.type.name === 'tableHeader') {
      isHeader = node.type.name === 'tableHeader';

      // Find column index by looking at siblings
      const rowNode = $pos.node(depth - 1);
      if (rowNode && rowNode.type.name === 'tableRow') {
        let idx = 0;
        const cellPos = $pos.before(depth);
        rowNode.forEach((child, offset) => {
          if ($pos.start(depth - 1) + offset < cellPos) {
            idx++;
          }
        });
        columnIndex = idx;
      }
      break;
    }
  }

  return { isHeader, columnIndex };
}

/**
 * Sort table by the specified column.
 */
function sortTableByColumn(editor: Editor, columnIndex: number, direction: 'asc' | 'desc'): void {
  const { state } = editor;
  const { selection } = state;
  const $pos = selection.$anchor;

  // Find the table node
  let tableNode: ProseMirrorNode | null = null;
  let tablePos = 0;

  for (let depth = $pos.depth; depth > 0; depth--) {
    const node = $pos.node(depth);
    if (node.type.name === 'table') {
      tableNode = node;
      tablePos = $pos.before(depth);
      break;
    }
  }

  if (!tableNode) return;

  // Collect rows with their sort values
  interface RowData {
    node: ProseMirrorNode;
    sortValue: string;
    isHeader: boolean;
  }

  const rows: RowData[] = [];

  tableNode.forEach((row) => {
    if (row.type.name !== 'tableRow') return;

    // Check if this is a header row (all cells are tableHeader)
    let isHeader = true;
    let cellIndex = 0;
    let sortValue = '';

    row.forEach((cell) => {
      if (cell.type.name !== 'tableHeader') {
        isHeader = false;
      }

      if (cellIndex === columnIndex) {
        // Extract text content from cell
        cell.forEach((paragraph) => {
          paragraph.forEach((textNode) => {
            if (textNode.isText && textNode.text) {
              sortValue += textNode.text;
            }
          });
        });
      }
      cellIndex++;
    });

    rows.push({ node: row, sortValue: sortValue.toLowerCase().trim(), isHeader });
  });

  // Separate header rows from data rows
  const headerRows = rows.filter((r) => r.isHeader);
  const dataRows = rows.filter((r) => !r.isHeader);

  // Sort data rows
  dataRows.sort((a, b) => {
    // Try numeric sort
    const numA = parseFloat(a.sortValue);
    const numB = parseFloat(b.sortValue);

    if (!isNaN(numA) && !isNaN(numB)) {
      return direction === 'asc' ? numA - numB : numB - numA;
    }

    // Fall back to string sort
    const cmp = a.sortValue.localeCompare(b.sortValue);
    return direction === 'asc' ? cmp : -cmp;
  });

  // Reconstruct the table with sorted rows
  const sortedRows = [...headerRows, ...dataRows];

  // Create new table content
  const newTableContent = sortedRows.map((r) => r.node);

  // Replace table content using transaction
  const tr = state.tr;
  const tableStart = tablePos + 1; // Inside the table node

  // Delete all existing rows and insert sorted ones
  let deleteFrom = tableStart;
  let deleteTo = tablePos + tableNode.nodeSize - 1;

  // Create a new table node with sorted content
  const newTable = tableNode.type.create(tableNode.attrs, newTableContent);

  tr.replaceWith(tablePos, tablePos + tableNode.nodeSize, newTable);

  editor.view.dispatch(tr);
  editor.commands.focus();
}

export function TableContextMenu({ editor }: TableContextMenuProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [position, setPosition] = useState<MenuPosition>({ x: 0, y: 0 });
  const [cellInfo, setCellInfo] = useState<CellInfo | null>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  const handleContextMenu = useCallback(
    (event: MouseEvent) => {
      if (!editor) return;

      // Check if we're inside a table
      const target = event.target as HTMLElement;
      const tableCell = target.closest('td, th');

      if (!tableCell) {
        setIsOpen(false);
        return;
      }

      // Check if the editor has table commands available
      if (!editor.can().deleteTable()) {
        setIsOpen(false);
        return;
      }

      event.preventDefault();

      // Get cell info for context-aware menu options
      const info = getSelectedCellInfo(editor);
      setCellInfo(info);

      // Position menu, ensuring it stays within viewport
      let x = event.clientX;
      let y = event.clientY;

      setPosition({ x, y });
      setIsOpen(true);
    },
    [editor]
  );

  const handleClick = useCallback((event: MouseEvent) => {
    // Don't close if clicking inside the menu
    if (menuRef.current?.contains(event.target as Node)) {
      return;
    }
    setIsOpen(false);
  }, []);

  const handleKeyDown = useCallback((event: KeyboardEvent) => {
    if (event.key === 'Escape') {
      setIsOpen(false);
    }
  }, []);

  useEffect(() => {
    document.addEventListener('contextmenu', handleContextMenu);
    document.addEventListener('click', handleClick);
    document.addEventListener('keydown', handleKeyDown);

    return () => {
      document.removeEventListener('contextmenu', handleContextMenu);
      document.removeEventListener('click', handleClick);
      document.removeEventListener('keydown', handleKeyDown);
    };
  }, [handleContextMenu, handleClick, handleKeyDown]);

  if (!isOpen || !editor) return null;

  const menuItems = [
    // Sort options (only show when in a header cell or any cell)
    {
      label: 'Sort A → Z',
      icon: '↑',
      action: () => {
        if (cellInfo) {
          sortTableByColumn(editor, cellInfo.columnIndex, 'asc');
        }
      },
      canRun: () => cellInfo !== null,
    },
    {
      label: 'Sort Z → A',
      icon: '↓',
      action: () => {
        if (cellInfo) {
          sortTableByColumn(editor, cellInfo.columnIndex, 'desc');
        }
      },
      canRun: () => cellInfo !== null,
    },
    { divider: true },
    {
      label: 'Add row above',
      icon: '⬆',
      action: () => editor.chain().focus().addRowBefore().run(),
      canRun: () => editor.can().addRowBefore(),
    },
    {
      label: 'Add row below',
      icon: '⬇',
      action: () => editor.chain().focus().addRowAfter().run(),
      canRun: () => editor.can().addRowAfter(),
    },
    {
      label: 'Delete row',
      icon: '⊖',
      action: () => editor.chain().focus().deleteRow().run(),
      canRun: () => editor.can().deleteRow(),
      danger: true,
    },
    { divider: true },
    {
      label: 'Add column left',
      icon: '⬅',
      action: () => editor.chain().focus().addColumnBefore().run(),
      canRun: () => editor.can().addColumnBefore(),
    },
    {
      label: 'Add column right',
      icon: '➡',
      action: () => editor.chain().focus().addColumnAfter().run(),
      canRun: () => editor.can().addColumnAfter(),
    },
    {
      label: 'Delete column',
      icon: '⊖',
      action: () => editor.chain().focus().deleteColumn().run(),
      canRun: () => editor.can().deleteColumn(),
      danger: true,
    },
    { divider: true },
    {
      label: 'Toggle header row',
      icon: '▤',
      action: () => editor.chain().focus().toggleHeaderRow().run(),
      canRun: () => editor.can().toggleHeaderRow(),
    },
    {
      label: 'Toggle header column',
      icon: '▥',
      action: () => editor.chain().focus().toggleHeaderColumn().run(),
      canRun: () => editor.can().toggleHeaderColumn(),
    },
    { divider: true },
    {
      label: 'Merge cells',
      icon: '⊞',
      action: () => editor.chain().focus().mergeCells().run(),
      canRun: () => editor.can().mergeCells(),
    },
    {
      label: 'Split cell',
      icon: '⊟',
      action: () => editor.chain().focus().splitCell().run(),
      canRun: () => editor.can().splitCell(),
    },
    { divider: true },
    {
      label: 'Delete table',
      icon: '🗑',
      action: () => editor.chain().focus().deleteTable().run(),
      canRun: () => editor.can().deleteTable(),
      danger: true,
    },
  ];

  return (
    <div
      ref={menuRef}
      className="table-context-menu"
      style={{
        left: position.x,
        top: position.y,
      }}
    >
      {menuItems.map((item, index) => {
        if ('divider' in item && item.divider) {
          return <div key={index} className="table-context-menu-divider" />;
        }

        const menuItem = item as {
          label: string;
          icon: string;
          action: () => void;
          canRun: () => boolean;
          danger?: boolean;
        };

        if (!menuItem.canRun()) return null;

        return (
          <div
            key={menuItem.label}
            className={`table-context-menu-item ${menuItem.danger ? 'danger' : ''}`}
            onClick={() => {
              menuItem.action();
              setIsOpen(false);
            }}
          >
            <span>{menuItem.icon}</span>
            <span>{menuItem.label}</span>
          </div>
        );
      })}
    </div>
  );
}
