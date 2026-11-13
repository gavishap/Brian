import { useQueryClient } from '@tanstack/react-query';
import * as Notifications from 'expo-notifications';
import { useRouter } from 'expo-router';
import { useEffect } from 'react';
import { AppState } from 'react-native';

import { keys } from '@/api/queries';

import { eventFromReceived, eventFromResponse } from './events';
import { enqueueEvents, flushEvents } from './queue';
import { registerPushToken } from './register';
import { configureNotifications } from './setup';

// Responses already routed in this JS session (the cold-start response can also reach the listener).
const handled = new Set<string>();

/**
 * While signed in: keep the push token registered, record every reaction to a nudge, and open the
 * nudge screen when one is tapped (including the tap that launched the app).
 */
export function useNotificationObserver(enabled: boolean) {
  const router = useRouter();
  const queryClient = useQueryClient();

  useEffect(() => {
    if (!enabled) return;

    void configureNotifications().catch(() => undefined);
    void registerPushToken({ prompt: false }).catch(() => undefined);
    void flushEvents();

    const onResponse = (response: Notifications.NotificationResponse) => {
      const event = eventFromResponse(response);
      Notifications.clearLastNotificationResponse();
      if (!event || handled.has(event.client_event_id)) return;
      handled.add(event.client_event_id);
      void enqueueEvents([event]);
      void queryClient.invalidateQueries({ queryKey: keys.nudges });
      if (event.type === 'dismissed') return;
      if (event.type === 'action') {
        void queryClient.invalidateQueries({ queryKey: ['goals'] });
      }
      router.push({
        pathname: '/nudge/[id]',
        params: {
          id: event.nudge_id,
          ...(event.action_id ? { action: event.action_id } : {}),
          ...(event.text ? { reply: event.text } : {}),
        },
      });
    };

    const launchResponse = Notifications.getLastNotificationResponse();
    if (launchResponse) onResponse(launchResponse);

    const responses = Notifications.addNotificationResponseReceivedListener(onResponse);
    const received = Notifications.addNotificationReceivedListener((notification) => {
      const event = eventFromReceived(notification);
      if (event) {
        void enqueueEvents([event]);
        void queryClient.invalidateQueries({ queryKey: keys.nudges });
      }
    });
    const appState = AppState.addEventListener('change', (state) => {
      if (state === 'active') void flushEvents();
    });
    return () => {
      responses.remove();
      received.remove();
      appState.remove();
    };
  }, [enabled, router, queryClient]);
}
