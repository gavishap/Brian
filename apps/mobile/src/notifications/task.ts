import * as Notifications from 'expo-notifications';
import * as TaskManager from 'expo-task-manager';

import { dataFromTaskPayload, eventFromResponse, nudgeIdOf } from './events';
import { enqueueEvents, flushEvents } from './queue';

/**
 * Runs in the background (Android: also when the app was killed) for action-button taps and for
 * nudges delivered while the app is backgrounded. Defined at module scope from `index.ts` so the
 * OS can start it before any screen mounts.
 */
export const NOTIFICATION_TASK = 'brian-notification-task';

TaskManager.defineTask<Notifications.NotificationTaskPayload>(NOTIFICATION_TASK, async ({ data, error }) => {
  if (error || !data) return Notifications.BackgroundNotificationTaskResult.Failed;
  try {
    if ('actionIdentifier' in data) {
      const event = eventFromResponse(data);
      if (event) {
        await enqueueEvents([event]);
        // A button that doesn't open the app leaves the notification up; clear it.
        await Notifications.dismissNotificationAsync(data.notification.request.identifier).catch(() => undefined);
      }
    } else {
      const payload = dataFromTaskPayload(data);
      const nudgeId = nudgeIdOf(payload);
      if (nudgeId) {
        await enqueueEvents([
          {
            nudge_id: nudgeId,
            type: 'received',
            occurred_at: new Date().toISOString(),
            client_event_id: `recv:${nudgeId}`,
          },
        ]);
      }
    }
    await flushEvents();
    return Notifications.BackgroundNotificationTaskResult.NewData;
  } catch {
    return Notifications.BackgroundNotificationTaskResult.Failed;
  }
});

Notifications.registerTaskAsync(NOTIFICATION_TASK).catch(() => {
  // Not available in Expo Go / on web; foreground listeners still record reactions.
});
