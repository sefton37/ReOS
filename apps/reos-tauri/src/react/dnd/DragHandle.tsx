/**
 * DragHandle - Grip icon that appears on block hover for drag and drop.
 */

interface DragHandleProps {
  onDragStart: () => void;
  onDragEnd: () => void;
}

export function DragHandle({ onDragStart, onDragEnd }: DragHandleProps) {
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.effectAllowed = 'move';
        onDragStart();
      }}
      onDragEnd={onDragEnd}
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        width: '20px',
        height: '20px',
        borderRadius: '4px',
        cursor: 'grab',
        opacity: 0.4,
        transition: 'opacity 0.1s, background 0.1s',
      }}
      onMouseEnter={(e) => {
        e.currentTarget.style.opacity = '1';
        e.currentTarget.style.background = 'rgba(255, 255, 255, 0.1)';
      }}
      onMouseLeave={(e) => {
        e.currentTarget.style.opacity = '0.4';
        e.currentTarget.style.background = 'transparent';
      }}
      title="Drag to reorder"
    >
      {/* Six-dot grip icon */}
      <svg
        width="10"
        height="14"
        viewBox="0 0 10 14"
        fill="currentColor"
        style={{ color: 'rgba(255, 255, 255, 0.6)' }}
      >
        <circle cx="2" cy="2" r="1.5" />
        <circle cx="8" cy="2" r="1.5" />
        <circle cx="2" cy="7" r="1.5" />
        <circle cx="8" cy="7" r="1.5" />
        <circle cx="2" cy="12" r="1.5" />
        <circle cx="8" cy="12" r="1.5" />
      </svg>
    </div>
  );
}

export default DragHandle;
