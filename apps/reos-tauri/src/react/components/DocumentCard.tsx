/**
 * DocumentCard - Visual representation of an inserted document in the editor.
 *
 * Displays document info (filename, size, chunks) and provides delete action.
 */

import { NodeViewWrapper, type NodeViewProps } from '@tiptap/react';

// File type icons
const FILE_ICONS: Record<string, string> = {
  pdf: '📕',
  docx: '📘',
  doc: '📘',
  txt: '📝',
  md: '📝',
  csv: '📊',
  xlsx: '📗',
  xls: '📗',
};

function getFileIcon(fileType: string): string {
  return FILE_ICONS[fileType.toLowerCase()] || '📄';
}

function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function DocumentCard({ node, deleteNode }: NodeViewProps) {
  const { fileName, fileSize, fileType, chunkCount } = node.attrs as {
    documentId: string;
    fileName: string;
    fileSize: number;
    fileType: string;
    chunkCount: number;
  };

  return (
    <NodeViewWrapper className="document-block-wrapper">
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '12px',
          padding: '12px 16px',
          background: 'rgba(34, 197, 94, 0.08)',
          border: '1px solid rgba(34, 197, 94, 0.2)',
          borderRadius: '8px',
          margin: '8px 0',
          userSelect: 'none',
        }}
        contentEditable={false}
      >
        {/* File icon */}
        <div
          style={{
            fontSize: '28px',
            flexShrink: 0,
          }}
        >
          {getFileIcon(fileType)}
        </div>

        {/* Document info */}
        <div
          style={{
            flex: 1,
            minWidth: 0,
          }}
        >
          <div
            style={{
              fontSize: '14px',
              fontWeight: 500,
              color: '#e5e7eb',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}
          >
            {fileName}
          </div>
          <div
            style={{
              fontSize: '12px',
              color: 'rgba(255, 255, 255, 0.5)',
              marginTop: '2px',
            }}
          >
            {formatFileSize(fileSize)} • {chunkCount} chunks indexed
          </div>
        </div>

        {/* Delete button */}
        <button
          onClick={deleteNode}
          style={{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid rgba(239, 68, 68, 0.3)',
            borderRadius: '4px',
            color: '#ef4444',
            cursor: 'pointer',
            padding: '4px 8px',
            fontSize: '12px',
            fontWeight: 500,
            transition: 'all 0.2s',
          }}
          onMouseEnter={(e) => {
            e.currentTarget.style.background = 'rgba(239, 68, 68, 0.2)';
          }}
          onMouseLeave={(e) => {
            e.currentTarget.style.background = 'rgba(239, 68, 68, 0.1)';
          }}
          title="Remove from editor (document stays in knowledge base)"
        >
          Remove
        </button>
      </div>
    </NodeViewWrapper>
  );
}

export default DocumentCard;
