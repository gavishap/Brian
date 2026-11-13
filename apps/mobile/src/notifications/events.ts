import type { NudgeEvent } from '@/api/types';
import { stableEventId } from '@/lib/ids';

/** `Notifications.DEFAULT_ACTION_IDENTIFIER`: the user tapped the notification itself. */
export const DEFAULT_ACTION = 'expo.modules.notifications.actions.DEFAULT';
/** iOS reports an explicit dismissal with this action when the category has `customDismissAction`. */
export const IOS_DISMISS_ACTION = 'com.apple.UNNotificationDismissActionIdentifier';

type NotificationLike = {
  request: { identifier: string; content: { data?: Record<string, unknown> | null } };
};

type ResponseLike = {
  notification: NotificationLike;
  actionIdentifier: string;
  userText?: string;
};

/** The nudge id carried in a push's data payload ({kind: "nudge", nudge_id, goal_id}), if any. */
export function nudgeIdOf(data: Record<string, unknown> | null | undefined): string | null {
  if (!data || data.kind !== 'nudge' || typeof data.nudge_id !== 'string') return null;
  return data.nudge_id;
}

/** Map a tap / action button / dismissal to the API's nudge event. Null when it isn't a nudge. */
export function eventFromResponse(response: ResponseLike, now: Date = new Date()): NudgeEvent | null {
  const { notification, actionIdentifier } = response;
  const nudgeId = nudgeIdOf(notification.request.content.data);
  if (!nudgeId) return null;
  const text = response.userText?.trim() || undefined;
  const base = {
    nudge_id: nudgeId,
    occurred_at: now.toISOString(),
    client_event_id: stableEventId('resp', notification.request.identifier, actionIdentifier),
  };
  if (actionIdentifier === DEFAULT_ACTION) return { ...base, type: 'opened' };
  if (actionIdentifier === IOS_DISMISS_ACTION) return { ...base, type: 'dismissed' };
  if (actionIdentifier === 'reply' && !text) return { ...base, type: 'opened' };
  return { ...base, type: 'action', action_id: actionIdentifier, ...(text ? { text } : {}) };
}

/** A nudge arrived while the app was running (delivery confirmation). */
export function eventFromReceived(notification: NotificationLike, now: Date = new Date()): NudgeEvent | null {
  const nudgeId = nudgeIdOf(notification.request.content.data);
  if (!nudgeId) return null;
  return {
    nudge_id: nudgeId,
    type: 'received',
    occurred_at: now.toISOString(),
    client_event_id: stableEventId('recv', notification.request.identifier),
  };
}

/**
 * Data of a notification delivered to the background task (not a response). Android hands the
 * payload over as a JSON string; shapes differ by platform, so look in the known places.
 */
export function dataFromTaskPayload(payload: { data?: Record<string, unknown> | null }): Record<string, unknown> | null {
  const data = payload.data ?? null;
  if (!data) return null;
  for (const key of ['dataString', 'body']) {
    const raw = data[key];
    if (typeof raw === 'string') {
      try {
        const parsed: unknown = JSON.parse(raw);
        if (parsed && typeof parsed === 'object') return parsed as Record<string, unknown>;
      } catch {
        // not JSON; keep looking
      }
    }
  }
  return data;
}
