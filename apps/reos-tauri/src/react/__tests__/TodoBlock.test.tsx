/**
 * Tests for TodoBlock component.
 */

import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { TodoBlock } from '../blocks/TodoBlock';
import type { Block, RichTextSpan } from '../types';

// Helper to create a todo block
function createTodoBlock(overrides: Partial<Block> = {}): Block {
  return {
    id: 'todo-1',
    type: 'to_do',
    act_id: 'act-1',
    parent_id: null,
    page_id: 'page-1',
    scene_id: null,
    position: 0,
    created_at: '2026-01-24T10:00:00Z',
    updated_at: '2026-01-24T10:00:00Z',
    rich_text: [
      {
        id: 'span-1',
        block_id: 'todo-1',
        position: 0,
        content: 'Test todo item',
        bold: false,
        italic: false,
        strikethrough: false,
        code: false,
        underline: false,
        color: null,
        background_color: null,
        link_url: null,
      },
    ],
    properties: { checked: false },
    children: [],
    ...overrides,
  };
}

describe('TodoBlock', () => {
  it('renders unchecked todo item', () => {
    const block = createTodoBlock();
    render(<TodoBlock block={block} />);

    expect(screen.getByText('Test todo item')).toBeInTheDocument();
    expect(screen.getByRole('checkbox')).not.toBeChecked();
  });

  it('renders checked todo item', () => {
    const block = createTodoBlock({ properties: { checked: true } });
    render(<TodoBlock block={block} />);

    expect(screen.getByRole('checkbox')).toBeChecked();
  });

  it('applies strikethrough style when checked', () => {
    const block = createTodoBlock({ properties: { checked: true } });
    render(<TodoBlock block={block} />);

    const textContainer = screen.getByText('Test todo item').closest('div');
    expect(textContainer).toHaveStyle({ textDecoration: 'line-through' });
  });

  it('does not apply strikethrough when unchecked', () => {
    const block = createTodoBlock({ properties: { checked: false } });
    render(<TodoBlock block={block} />);

    const textContainer = screen.getByText('Test todo item').closest('div');
    expect(textContainer).toHaveStyle({ textDecoration: 'none' });
  });

  it('calls onUpdate when checkbox is toggled', () => {
    const onUpdate = vi.fn();
    const block = createTodoBlock({ properties: { checked: false } });

    render(<TodoBlock block={block} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByRole('checkbox'));

    expect(onUpdate).toHaveBeenCalledTimes(1);
    expect(onUpdate).toHaveBeenCalledWith({
      ...block,
      properties: { checked: true },
    });
  });

  it('toggles from checked to unchecked', () => {
    const onUpdate = vi.fn();
    const block = createTodoBlock({ properties: { checked: true } });

    render(<TodoBlock block={block} onUpdate={onUpdate} />);

    fireEvent.click(screen.getByRole('checkbox'));

    expect(onUpdate).toHaveBeenCalledWith({
      ...block,
      properties: { checked: false },
    });
  });

  it('does not call onUpdate when onUpdate is not provided', () => {
    const block = createTodoBlock();

    render(<TodoBlock block={block} />);

    // Should not throw
    fireEvent.click(screen.getByRole('checkbox'));
  });

  describe('nested children', () => {
    it('renders nested todo items', () => {
      const parentBlock = createTodoBlock({
        id: 'parent-todo',
        rich_text: [
          {
            id: 'span-parent',
            block_id: 'parent-todo',
            position: 0,
            content: 'Parent todo',
            bold: false,
            italic: false,
            strikethrough: false,
            code: false,
            underline: false,
            color: null,
            background_color: null,
            link_url: null,
          },
        ],
        children: [
          createTodoBlock({
            id: 'child-todo',
            parent_id: 'parent-todo',
            rich_text: [
              {
                id: 'span-child',
                block_id: 'child-todo',
                position: 0,
                content: 'Child todo',
                bold: false,
                italic: false,
                strikethrough: false,
                code: false,
                underline: false,
                color: null,
                background_color: null,
                link_url: null,
              },
            ],
          }),
        ],
      });

      render(<TodoBlock block={parentBlock} />);

      expect(screen.getByText('Parent todo')).toBeInTheDocument();
      expect(screen.getByText('Child todo')).toBeInTheDocument();
    });

    it('renders two checkboxes for parent and child', () => {
      const parentBlock = createTodoBlock({
        id: 'parent-todo',
        children: [createTodoBlock({ id: 'child-todo', parent_id: 'parent-todo' })],
      });

      render(<TodoBlock block={parentBlock} />);

      const checkboxes = screen.getAllByRole('checkbox');
      expect(checkboxes).toHaveLength(2);
    });
  });
});
