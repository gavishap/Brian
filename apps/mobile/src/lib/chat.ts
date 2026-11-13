import { fetch } from 'expo/fetch';

import { ApiError } from '@/api/client';
import type { ChatRequest, ChatStreamEvent } from '@/api/types';

import { config } from './config';
import { SSEParser } from './sse';
import { getAccessToken } from './supabase';

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

/**
 * Send a message to Brian and yield the streamed reply events. Uses `expo/fetch`, whose response
 * body is a ReadableStream on iOS and Android (React Native's built-in fetch buffers the body).
 */
export async function* streamChat(body: ChatRequest, signal?: AbortSignal): AsyncGenerator<ChatStreamEvent> {
  const token = await getAccessToken();
  const response = await fetch(`${config.apiUrl}/v1/chat`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify(body),
    signal,
  });
  if (!response.ok || !response.body) {
    let detail: unknown = null;
    try {
      detail = await response.json();
    } catch {
      detail = null;
    }
    throw new ApiError(response.status, detail);
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SSEParser();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      for (const event of parser.push(decoder.decode(value, { stream: true }))) {
        const parsed = parseChatEvent(event.data);
        if (parsed) yield parsed;
      }
    }
    for (const event of parser.push(decoder.decode())) {
      const parsed = parseChatEvent(event.data);
      if (parsed) yield parsed;
    }
    for (const event of parser.flush()) {
      const parsed = parseChatEvent(event.data);
      if (parsed) yield parsed;
    }
  } finally {
    reader.releaseLock();
  }
}
