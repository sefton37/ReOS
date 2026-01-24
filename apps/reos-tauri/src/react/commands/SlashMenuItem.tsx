/**
 * SlashMenuItem - Individual command item in the slash menu.
 */

import type { SlashCommand } from './slashCommands';

interface SlashMenuItemProps {
  command: SlashCommand;
  isSelected: boolean;
  onClick: () => void;
}

export function SlashMenuItem({
  command,
  isSelected,
  onClick,
}: SlashMenuItemProps) {
  return (
    <button
      onClick={onClick}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: '12px',
        width: '100%',
        padding: '8px 12px',
        border: 'none',
        background: isSelected ? 'rgba(34, 197, 94, 0.15)' : 'transparent',
        borderRadius: '6px',
        cursor: 'pointer',
        textAlign: 'left',
        transition: 'background 0.1s',
      }}
      onMouseEnter={(e) => {
        if (!isSelected) {
          e.currentTarget.style.background = 'rgba(255, 255, 255, 0.05)';
        }
      }}
      onMouseLeave={(e) => {
        if (!isSelected) {
          e.currentTarget.style.background = 'transparent';
        }
      }}
    >
      <span
        style={{
          width: '28px',
          height: '28px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'rgba(255, 255, 255, 0.1)',
          borderRadius: '6px',
          fontSize: '14px',
          color: isSelected ? '#22c55e' : 'rgba(255, 255, 255, 0.7)',
        }}
      >
        {command.icon}
      </span>
      <div style={{ flex: 1, minWidth: 0 }}>
        <div
          style={{
            color: isSelected ? '#22c55e' : '#f3f4f6',
            fontSize: '13px',
            fontWeight: 500,
          }}
        >
          {command.label}
        </div>
        <div
          style={{
            color: 'rgba(255, 255, 255, 0.4)',
            fontSize: '11px',
            marginTop: '1px',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
            whiteSpace: 'nowrap',
          }}
        >
          {command.description}
        </div>
      </div>
    </button>
  );
}

export default SlashMenuItem;
