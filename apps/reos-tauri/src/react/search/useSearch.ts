/**
 * useSearch - Hook for searching blocks across acts.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import type { Block } from '../types';

interface SearchResult {
  block: Block;
  context: string;
  matchStart: number;
  matchEnd: number;
}

interface UseSearchOptions {
  kernelRequest: (method: string, params: Record<string, unknown>) => Promise<unknown>;
  debounceMs?: number;
}

interface UseSearchResult {
  query: string;
  setQuery: (query: string) => void;
  results: SearchResult[];
  isLoading: boolean;
  error: string | null;
  search: (query: string) => Promise<void>;
}

export function useSearch(options: UseSearchOptions): UseSearchResult {
  const { kernelRequest, debounceMs = 300 } = options;

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const debounceTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const search = useCallback(
    async (searchQuery: string) => {
      if (!searchQuery.trim()) {
        setResults([]);
        setIsLoading(false);
        return;
      }

      setIsLoading(true);
      setError(null);

      try {
        const result = (await kernelRequest('blocks/search', {
          query: searchQuery.trim(),
        })) as { blocks: Block[] };

        const searchResults: SearchResult[] = (result.blocks ?? []).map((block) => {
          const text = block.rich_text.map((s) => s.content).join('');
          const lowerText = text.toLowerCase();
          const lowerQuery = searchQuery.toLowerCase();
          const matchStart = lowerText.indexOf(lowerQuery);
          const matchEnd = matchStart + searchQuery.length;

          // Create context around the match
          const contextStart = Math.max(0, matchStart - 30);
          const contextEnd = Math.min(text.length, matchEnd + 30);
          let context = text.slice(contextStart, contextEnd);
          if (contextStart > 0) context = '...' + context;
          if (contextEnd < text.length) context = context + '...';

          return {
            block,
            context,
            matchStart: matchStart - contextStart + (contextStart > 0 ? 3 : 0),
            matchEnd: matchEnd - contextStart + (contextStart > 0 ? 3 : 0),
          };
        });

        setResults(searchResults);
      } catch (e) {
        console.error('Search failed:', e);
        setError(e instanceof Error ? e.message : 'Search failed');
        setResults([]);
      } finally {
        setIsLoading(false);
      }
    },
    [kernelRequest],
  );

  // Debounced search on query change
  useEffect(() => {
    if (debounceTimer.current) {
      clearTimeout(debounceTimer.current);
    }

    if (!query.trim()) {
      setResults([]);
      setIsLoading(false);
      return;
    }

    setIsLoading(true);

    debounceTimer.current = setTimeout(() => {
      void search(query);
    }, debounceMs);

    return () => {
      if (debounceTimer.current) {
        clearTimeout(debounceTimer.current);
      }
    };
  }, [query, debounceMs, search]);

  return {
    query,
    setQuery,
    results,
    isLoading,
    error,
    search,
  };
}

export default useSearch;
