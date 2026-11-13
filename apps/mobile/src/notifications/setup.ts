import * as Notifications from 'expo-notifications';
import { AndroidImportance } from 'expo-notifications';
import { Platform } from 'react-native';

/** Android channel the API sends nudges on (`channelId: "nudges"`). */
export const NUDGE_CHANNEL_ID = 'nudges';

/** Action identifiers; the API maps them to outcomes (done -> completed, snooze -> snoozed, ...). */
export const Actions = {
  done: 'done',
  snooze: 'snooze',
  reply: 'reply',
  notHelpful: 'not_helpful',
} as const;

/** Category ids the API puts in `categoryId`. */
export const Categories = {
  action: 'nudge_action',
  reflect: 'nudge_reflect',
} as const;

// On Android a background task receives action taps even when the app is killed, so buttons can
// work without opening the app. iOS only runs our JS for an action of a killed app if the action
// opens it, so there every action brings the app forward (otherwise the reaction would be lost).
const OPENS_APP = Platform.OS === 'ios';

let configured: Promise<void> | null = null;

/** Idempotent: foreground presentation, the Android channel and the action-button categories. */
export function configureNotifications(): Promise<void> {
  configured ??= doConfigure().catch((error: unknown) => {
    configured = null;
    throw error;
  });
  return configured;
}

async function doConfigure(): Promise<void> {
  Notifications.setNotificationHandler({
    handleNotification: async () => ({
      shouldShowBanner: true,
      shouldShowList: true,
      shouldPlaySound: true,
      shouldSetBadge: false,
    }),
  });

  if (Platform.OS === 'android') {
    await Notifications.setNotificationChannelAsync(NUDGE_CHANNEL_ID, {
      name: 'Nudges',
      description: 'Check-ins and reminders from Brian about your goals',
      importance: AndroidImportance.HIGH,
      vibrationPattern: [0, 180, 120, 180],
      lightColor: '#4F46E5',
    });
  }

  const reply: Notifications.NotificationAction = {
    identifier: Actions.reply,
    buttonTitle: 'Reply',
    textInput: { submitButtonTitle: 'Send', placeholder: 'Tell Brian how it’s going…' },
    options: { opensAppToForeground: OPENS_APP },
  };

  // `customDismissAction` makes iOS report explicit dismissals (a useful negative signal).
  await Notifications.setNotificationCategoryAsync(
    Categories.action,
    [
      { identifier: Actions.done, buttonTitle: 'Done ✅', options: { opensAppToForeground: OPENS_APP } },
      { identifier: Actions.snooze, buttonTitle: 'Later', options: { opensAppToForeground: OPENS_APP } },
      reply,
    ],
    { customDismissAction: true },
  );
  await Notifications.setNotificationCategoryAsync(
    Categories.reflect,
    [
      reply,
      {
        identifier: Actions.notHelpful,
        buttonTitle: 'Less of these',
        options: { opensAppToForeground: OPENS_APP, isDestructive: true },
      },
    ],
    { customDismissAction: true },
  );
}
