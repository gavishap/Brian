import AsyncStorage from '@react-native-async-storage/async-storage';

import { api } from '@/api/client';
import type { NudgeEvent } from '@/api/types';
import { getAccessToken } from '@/lib/supabase';

/**
 * Persistent outbox for nudge reactions. Events are written to storage first and sent in batches
 * when possible, so a reaction made offline (or from a background task) is never lost. Every event
 * carries an idempotency key, so resending after a timeout cannot double count.
 */
const STORAGE_KEY = 'brian.nudge-events.v1';
const MAX_QUEUE = 500;
const BATCH = 100;
const MAX_BACKOFF_MS = 5 * 60 * 1000;

let chain: Promise<unknown> = Promise.resolve();
let flushing: Promise<void> | null = null;
let backoffMs = 0;
let retryTimer: ReturnType<typeof setTimeout> | null = null;

/** Serialize read-modify-write cycles on the stored queue. */
function locked<T>(fn: () => Promise<T>): Promise<T> {
  const next = chain.then(fn, fn);
  chain = next.catch(() => undefined);
  return next;
}

async function read(): Promise<NudgeEvent[]> {
  const raw = await AsyncStorage.getItem(STORAGE_KEY);
  if (!raw) return [];
  try {
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as NudgeEvent[]) : [];
  } catch {
    return [];
  }
}

async function write(events: NudgeEvent[]): Promise<void> {
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(events.slice(-MAX_QUEUE)));
}

export async function enqueueEvents(events: NudgeEvent[]): Promise<void> {
  if (events.length === 0) return;
  await locked(async () => {
    const queue = await read();
    const seen = new Set(queue.map((e) => e.client_event_id));
    for (const event of events) {
      if (!seen.has(event.client_event_id)) {
        queue.push(event);
        seen.add(event.client_event_id);
      }
    }
    await write(queue);
  });
  void flushEvents();
}

export async function pendingEventCount(): Promise<number> {
  return (await read()).length;
}

/** Send queued events. Safe to call often; concurrent calls share one flush. */
export function flushEvents(): Promise<void> {
  flushing ??= doFlush().finally(() => {
    flushing = null;
  });
  return flushing;
}

function scheduleRetry(): void {
  backoffMs = Math.min(backoffMs ? backoffMs * 2 : 5000, MAX_BACKOFF_MS);
  if (retryTimer) clearTimeout(retryTimer);
  retryTimer = setTimeout(() => {
    retryTimer = null;
    void flushEvents();
  }, backoffMs);
}

async function removeSent(ids: Set<string>): Promise<void> {
  await locked(async () => {
    const queue = await read();
    await write(queue.filter((e) => !ids.has(e.client_event_id)));
  });
}

async function doFlush(): Promise<void> {
  if (!(await getAccessToken())) return; // flushed again after sign-in
  for (;;) {
    const batch = (await read()).slice(0, BATCH);
    if (batch.length === 0) {
      backoffMs = 0;
      return;
    }
    let status: number;
    try {
      const { response } = await api.POST('/v1/nudges/events', { body: { events: batch } });
      status = response.status;
    } catch {
      scheduleRetry(); // offline or server unreachable
      return;
    }
    if (status >= 200 && status < 300) {
      await removeSent(new Set(batch.map((e) => e.client_event_id)));
      backoffMs = 0;
      continue;
    }
    if (status === 401 || status === 408 || status === 429 || status >= 500) {
      scheduleRetry();
      return;
    }
    // Any other 4xx means the batch itself is invalid; retrying cannot fix it.
    console.warn(`Dropping ${batch.length} nudge events rejected with HTTP ${status}`);
    await removeSent(new Set(batch.map((e) => e.client_event_id)));
  }
}
