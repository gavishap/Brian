import type { ChatStreamEvent } from '@/api/types';

const EVENT_TYPES = new Set(['conversation', 'text', 'tool', 'done', 'error']);

/** Parse one SSE `data` payload into a chat event; unknown or malformed payloads are skipped. */
export function parseChatEvent(data: string): ChatStreamEvent | null {
  try {
    const value: unknown = JSON.parse(data);
    if (value && typeof value === 'object' && EVENT_TYPES.has((value as { type?: string }).type ?? '')) {
      return value as ChatStreamEvent;
    }
  } catch {
    // Not JSON (should not happen with this API); ignore rather than break the stream.
  }
  return null;
}
