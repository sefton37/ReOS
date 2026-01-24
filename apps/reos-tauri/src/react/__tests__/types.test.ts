/**
 * Tests for block type utilities.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  createBlock,
  createRichTextSpan,
  getBlockPlainText,
  isNestable,
  NESTABLE_TYPES,
  type Block,
} from '../types';

// Mock crypto.randomUUID
beforeEach(() => {
  let counter = 0;
  vi.spyOn(crypto, 'randomUUID').mockImplementation(
    () => `test-uuid-${counter++}` as `${string}-${string}-${string}-${string}-${string}`,
  );
});

describe('NESTABLE_TYPES', () => {
  it('includes page, lists, todo, and callout', () => {
    expect(NESTABLE_TYPES.has('page')).toBe(true);
    expect(NESTABLE_TYPES.has('bulleted_list')).toBe(true);
    expect(NESTABLE_TYPES.has('numbered_list')).toBe(true);
    expect(NESTABLE_TYPES.has('to_do')).toBe(true);
    expect(NESTABLE_TYPES.has('callout')).toBe(true);
  });

  it('excludes paragraph, headings, code, divider, scene', () => {
    expect(NESTABLE_TYPES.has('paragraph')).toBe(false);
    expect(NESTABLE_TYPES.has('heading_1')).toBe(false);
    expect(NESTABLE_TYPES.has('heading_2')).toBe(false);
    expect(NESTABLE_TYPES.has('heading_3')).toBe(false);
    expect(NESTABLE_TYPES.has('code')).toBe(false);
    expect(NESTABLE_TYPES.has('divider')).toBe(false);
    expect(NESTABLE_TYPES.has('scene')).toBe(false);
  });
});

describe('isNestable', () => {
  it('returns true for nestable types', () => {
    expect(isNestable('page')).toBe(true);
    expect(isNestable('bulleted_list')).toBe(true);
    expect(isNestable('to_do')).toBe(true);
  });

  it('returns false for non-nestable types', () => {
    expect(isNestable('paragraph')).toBe(false);
    expect(isNestable('code')).toBe(false);
    expect(isNestable('divider')).toBe(false);
  });
});

describe('createRichTextSpan', () => {
  it('creates a span with default formatting', () => {
    const span = createRichTextSpan('block-123', 'Hello world');

    expect(span.block_id).toBe('block-123');
    expect(span.content).toBe('Hello world');
    expect(span.position).toBe(0);
    expect(span.bold).toBe(false);
    expect(span.italic).toBe(false);
    expect(span.strikethrough).toBe(false);
    expect(span.code).toBe(false);
    expect(span.underline).toBe(false);
    expect(span.color).toBeNull();
    expect(span.background_color).toBeNull();
    expect(span.link_url).toBeNull();
  });

  it('uses provided position', () => {
    const span = createRichTextSpan('block-123', 'Test', 5);
    expect(span.position).toBe(5);
  });

  it('generates unique IDs', () => {
    const span1 = createRichTextSpan('block-123', 'First');
    const span2 = createRichTextSpan('block-123', 'Second');

    expect(span1.id).not.toBe(span2.id);
  });
});

describe('createBlock', () => {
  it('creates a paragraph block with defaults', () => {
    const block = createBlock('paragraph', 'act-123');

    expect(block.type).toBe('paragraph');
    expect(block.act_id).toBe('act-123');
    expect(block.parent_id).toBeNull();
    expect(block.page_id).toBeNull();
    expect(block.scene_id).toBeNull();
    expect(block.position).toBe(0);
    expect(block.rich_text).toEqual([]);
    expect(block.properties).toEqual({});
    expect(block.children).toEqual([]);
  });

  it('creates a block with page_id', () => {
    const block = createBlock('heading_1', 'act-123', 'page-456');

    expect(block.page_id).toBe('page-456');
    expect(block.parent_id).toBeNull();
  });

  it('creates a block with parent_id', () => {
    const block = createBlock('bulleted_list', 'act-123', null, 'parent-789');

    expect(block.page_id).toBeNull();
    expect(block.parent_id).toBe('parent-789');
  });

  it('includes timestamps', () => {
    const before = new Date().toISOString();
    const block = createBlock('paragraph', 'act-123');
    const after = new Date().toISOString();

    expect(block.created_at >= before).toBe(true);
    expect(block.created_at <= after).toBe(true);
    expect(block.updated_at).toBe(block.created_at);
  });
});

describe('getBlockPlainText', () => {
  it('returns empty string for block with no spans', () => {
    const block = createBlock('paragraph', 'act-123');
    expect(getBlockPlainText(block)).toBe('');
  });

  it('concatenates multiple spans', () => {
    const block: Block = {
      ...createBlock('paragraph', 'act-123'),
      rich_text: [
        { ...createRichTextSpan('b', 'Hello '), id: '1', position: 0 },
        { ...createRichTextSpan('b', 'world'), id: '2', position: 1, bold: true },
        { ...createRichTextSpan('b', '!'), id: '3', position: 2 },
      ],
    };

    expect(getBlockPlainText(block)).toBe('Hello world!');
  });

  it('ignores formatting when extracting text', () => {
    const block: Block = {
      ...createBlock('paragraph', 'act-123'),
      rich_text: [
        {
          ...createRichTextSpan('b', 'Formatted'),
          id: '1',
          bold: true,
          italic: true,
          link_url: 'https://example.com',
        },
      ],
    };

    expect(getBlockPlainText(block)).toBe('Formatted');
  });
});
