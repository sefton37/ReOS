import { describe, it, expect } from 'vitest';
import { z } from 'zod';

// Re-define schemas here for testing (mirrors main.ts)
const JsonRpcResponseSchema = z.object({
  jsonrpc: z.literal('2.0'),
  id: z.union([z.string(), z.number(), z.null()]).optional(),
  result: z.unknown().optional(),
  error: z
    .object({
      code: z.number(),
      message: z.string(),
      data: z.unknown().optional()
    })
    .optional()
});

describe('JsonRpcResponseSchema', () => {
  it('validates a successful response', () => {
    const response = {
      jsonrpc: '2.0',
      id: 1,
      result: { answer: 'Hello' }
    };
    const parsed = JsonRpcResponseSchema.parse(response);
    expect(parsed.result).toEqual({ answer: 'Hello' });
    expect(parsed.error).toBeUndefined();
  });

  it('validates an error response', () => {
    const response = {
      jsonrpc: '2.0',
      id: 1,
      error: {
        code: -32602,
        message: 'Invalid params'
      }
    };
    const parsed = JsonRpcResponseSchema.parse(response);
    expect(parsed.error?.code).toBe(-32602);
    expect(parsed.error?.message).toBe('Invalid params');
  });

  it('validates response with null id', () => {
    const response = {
      jsonrpc: '2.0',
      id: null,
      result: 'ok'
    };
    const parsed = JsonRpcResponseSchema.parse(response);
    expect(parsed.id).toBeNull();
  });

  it('validates response with string id', () => {
    const response = {
      jsonrpc: '2.0',
      id: 'req-123',
      result: {}
    };
    const parsed = JsonRpcResponseSchema.parse(response);
    expect(parsed.id).toBe('req-123');
  });

  it('rejects invalid jsonrpc version', () => {
    const response = {
      jsonrpc: '1.0',
      id: 1,
      result: {}
    };
    expect(() => JsonRpcResponseSchema.parse(response)).toThrow();
  });

  it('validates error with optional data field', () => {
    const response = {
      jsonrpc: '2.0',
      id: 1,
      error: {
        code: -32000,
        message: 'Server error',
        data: { details: 'Something went wrong' }
      }
    };
    const parsed = JsonRpcResponseSchema.parse(response);
    expect(parsed.error?.data).toEqual({ details: 'Something went wrong' });
  });
});

describe('KernelError', () => {
  // Test the error class behavior
  class KernelError extends Error {
    code: number;
    constructor(message: string, code: number) {
      super(message);
      this.name = 'KernelError';
      this.code = code;
    }
  }

  it('creates error with message and code', () => {
    const err = new KernelError('Invalid params', -32602);
    expect(err.message).toBe('Invalid params');
    expect(err.code).toBe(-32602);
    expect(err.name).toBe('KernelError');
  });

  it('is instanceof Error', () => {
    const err = new KernelError('Test', -1);
    expect(err instanceof Error).toBe(true);
  });
});
