/**
 * DropIndicator - Visual indicator for drop target position.
 */

interface DropIndicatorProps {
  position: 'before' | 'after' | 'inside';
  isVisible: boolean;
}

export function DropIndicator({ position, isVisible }: DropIndicatorProps) {
  if (!isVisible) {
    return null;
  }

  if (position === 'inside') {
    return (
      <div
        style={{
          position: 'absolute',
          inset: 0,
          border: '2px dashed rgba(34, 197, 94, 0.5)',
          borderRadius: '8px',
          background: 'rgba(34, 197, 94, 0.05)',
          pointerEvents: 'none',
        }}
      />
    );
  }

  const isTop = position === 'before';

  return (
    <div
      style={{
        position: 'absolute',
        left: 0,
        right: 0,
        height: '2px',
        background: '#22c55e',
        ...(isTop ? { top: '-1px' } : { bottom: '-1px' }),
        pointerEvents: 'none',
      }}
    >
      {/* Circle indicator at the start */}
      <div
        style={{
          position: 'absolute',
          left: '-4px',
          top: '-3px',
          width: '8px',
          height: '8px',
          borderRadius: '50%',
          background: '#22c55e',
        }}
      />
    </div>
  );
}

export default DropIndicator;
