/** 53-bit string hash (cyrb53): fast, deterministic, good enough to shorten identifiers. */
export function hash53(input: string, seed = 0): string {
  let h1 = 0xdeadbeef ^ seed;
  let h2 = 0x41c6ce57 ^ seed;
  for (let i = 0; i < input.length; i++) {
    const ch = input.charCodeAt(i);
    h1 = Math.imul(h1 ^ ch, 2654435761);
    h2 = Math.imul(h2 ^ ch, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^ Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507) ^ Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
}

/**
 * Idempotency key for an event derived from what happened (notification + action), not from when
 * it was observed. The same interaction seen twice (live listener and cold-start replay, or the
 * Android background task and the foreground listener) yields the same key, so the API stores it once.
 */
export function stableEventId(kind: string, notificationId: string, action = ''): string {
  const raw = `${kind}:${notificationId}:${action}`;
  if (raw.length >= 8 && raw.length <= 120) return raw;
  return `${kind}:${hash53(raw)}:${hash53(raw, 1)}`;
}
