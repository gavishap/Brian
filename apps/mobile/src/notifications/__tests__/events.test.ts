import { describe, expect, it } from '@jest/globals';

import { stableEventId } from '@/lib/ids';

import { DEFAULT_ACTION, IOS_DISMISS_ACTION, dataFromTaskPayload, eventFromReceived, eventFromResponse } from '../events';

const NOW = new Date('2026-11-13T18:00:00.000Z');
const NUDGE = '6f3a2a52-6f45-4b8c-9d8a-0c7a1c3e9b11';

function response(actionIdentifier: string, userText?: string, data: Record<string, unknown> = { kind: 'nudge', nudge_id: NUDGE }) {
  return {
    actionIdentifier,
    userText,
    notification: { request: { identifier: 'notif-123', content: { data } } },
  };
}

describe('eventFromResponse', () => {
  it('maps a tap to "opened"', () => {
    expect(eventFromResponse(response(DEFAULT_ACTION), NOW)).toEqual({
      nudge_id: NUDGE,
      type: 'opened',
      occurred_at: NOW.toISOString(),
      client_event_id: stableEventId('resp', 'notif-123', DEFAULT_ACTION),
    });
  });

  it('maps action buttons with their identifier', () => {
    expect(eventFromResponse(response('done'), NOW)).toMatchObject({ type: 'action', action_id: 'done' });
    expect(eventFromResponse(response('snooze'), NOW)).toMatchObject({ type: 'action', action_id: 'snooze' });
    expect(eventFromResponse(response('not_helpful'), NOW)).toMatchObject({ type: 'action', action_id: 'not_helpful' });
  });

  it('includes reply text, and treats an empty reply as opened', () => {
    expect(eventFromResponse(response('reply', '  ran 5k!  '), NOW)).toMatchObject({
      type: 'action',
      action_id: 'reply',
      text: 'ran 5k!',
    });
    expect(eventFromResponse(response('reply', '   '), NOW)).toMatchObject({ type: 'opened' });
  });

  it('maps the iOS dismiss action to "dismissed"', () => {
    expect(eventFromResponse(response(IOS_DISMISS_ACTION), NOW)).toMatchObject({ type: 'dismissed' });
  });

  it('ignores notifications that are not nudges', () => {
    expect(eventFromResponse(response(DEFAULT_ACTION, undefined, { kind: 'other' }), NOW)).toBeNull();
    expect(eventFromResponse(response(DEFAULT_ACTION, undefined, {}), NOW)).toBeNull();
  });

  it('gives the same interaction the same idempotency key', () => {
    const a = eventFromResponse(response('done'), NOW);
    const b = eventFromResponse(response('done'), new Date(NOW.getTime() + 5000));
    expect(a?.client_event_id).toBe(b?.client_event_id);
    expect(a?.client_event_id).not.toBe(eventFromResponse(response('snooze'), NOW)?.client_event_id);
  });

  it('keeps idempotency keys within the API limits for long notification ids', () => {
    const long = { ...response('done'), notification: { request: { identifier: 'x'.repeat(300), content: { data: { kind: 'nudge', nudge_id: NUDGE } } } } };
    const id = eventFromResponse(long, NOW)?.client_event_id ?? '';
    expect(id.length).toBeGreaterThanOrEqual(8);
    expect(id.length).toBeLessThanOrEqual(128);
  });
});

describe('eventFromReceived', () => {
  it('keys deliveries by nudge so every device reports once', () => {
    const event = eventFromReceived(response(DEFAULT_ACTION).notification, NOW);
    expect(event).toEqual({
      nudge_id: NUDGE,
      type: 'received',
      occurred_at: NOW.toISOString(),
      client_event_id: stableEventId('recv', NUDGE),
    });
  });
});

describe('dataFromTaskPayload', () => {
  it('parses the JSON string Android hands to background tasks', () => {
    const payload = { data: { dataString: JSON.stringify({ kind: 'nudge', nudge_id: NUDGE }) } };
    expect(dataFromTaskPayload(payload)).toEqual({ kind: 'nudge', nudge_id: NUDGE });
  });

  it('falls back to the raw object', () => {
    expect(dataFromTaskPayload({ data: { kind: 'nudge', nudge_id: NUDGE } })).toEqual({ kind: 'nudge', nudge_id: NUDGE });
    expect(dataFromTaskPayload({ data: null })).toBeNull();
  });
});
