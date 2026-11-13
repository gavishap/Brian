import AsyncStorage from '@react-native-async-storage/async-storage';
import Constants from 'expo-constants';
import * as Device from 'expo-device';
import { getCalendars } from 'expo-localization';
import * as Notifications from 'expo-notifications';
import { Platform } from 'react-native';

import { api, unwrap } from '@/api/client';

import { configureNotifications } from './setup';

const TOKEN_KEY = 'brian.expo-push-token';
const SIMULATOR_ID_KEY = 'brian.simulator-push-id';

export type PushRegistration =
  | { status: 'registered'; token: string }
  | { status: 'denied' | 'undetermined' | 'unsupported' | 'misconfigured' };

function projectId(): string | undefined {
  const fromConfig = (Constants.expoConfig?.extra as { eas?: { projectId?: string } } | undefined)?.eas?.projectId;
  return fromConfig ?? Constants.easConfig?.projectId;
}

export function deviceTimeZone(): string | undefined {
  return getCalendars()[0]?.timeZone ?? undefined;
}

export async function notificationPermission(): Promise<Notifications.PermissionStatus> {
  return (await Notifications.getPermissionsAsync()).status;
}

/**
 * Get this device's Expo push token and register it with the API.
 * With `prompt: false` it never shows the permission dialog (used on every app start to keep the
 * token fresh); onboarding calls it with `prompt: true` after explaining why.
 */
export async function registerPushToken({ prompt }: { prompt: boolean }): Promise<PushRegistration> {
  if (Platform.OS === 'web') return { status: 'unsupported' };
  await configureNotifications();

  // Ask even on a simulator: without permission iOS won't show the nudges pushed into it.
  let permission = await Notifications.getPermissionsAsync();
  if (permission.status !== 'granted' && prompt && permission.canAskAgain) {
    permission = await Notifications.requestPermissionsAsync();
  }
  if (permission.status !== 'granted') {
    return { status: permission.status === 'denied' ? 'denied' : 'undetermined' };
  }

  const token = await pushToken();
  if (!token) return { status: Device.isDevice ? 'misconfigured' : 'unsupported' };
  unwrap(
    await api.POST('/v1/devices', {
      body: {
        expo_push_token: token,
        platform: Platform.OS === 'ios' ? 'ios' : 'android',
        device_name: Device.deviceName ?? Device.modelName ?? null,
        app_version: Constants.expoConfig?.version ?? null,
        timezone: deviceTimeZone() ?? null,
      },
    }),
  );
  await AsyncStorage.setItem(TOKEN_KEY, token);
  return { status: 'registered', token };
}

/**
 * The token pushes are addressed to. On a physical device: the Expo push token. In the iOS
 * Simulator (development builds only): a local stand-in that a backend running on the same Mac
 * delivers with `xcrun simctl push` (see PUSH_SIMULATOR_BUNDLE_ID in services/api/.env.example).
 */
async function pushToken(): Promise<string | null> {
  if (!Device.isDevice) {
    return __DEV__ && Platform.OS === 'ios' ? simulatorToken() : null;
  }
  const id = projectId();
  if (!id) {
    console.warn('EAS_PROJECT_ID is not set; push notifications are disabled.');
    return null;
  }
  const { data } = await Notifications.getExpoPushTokenAsync({ projectId: id });
  return data;
}

async function simulatorToken(): Promise<string> {
  let id = await AsyncStorage.getItem(SIMULATOR_ID_KEY);
  if (!id) {
    id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`;
    await AsyncStorage.setItem(SIMULATOR_ID_KEY, id);
  }
  return `ExponentPushToken[simulator-${id}]`;
}

/** Stop pushes to this device for the signed-in account (call before signing out). */
export async function unregisterPushToken(): Promise<void> {
  const token = await AsyncStorage.getItem(TOKEN_KEY);
  if (!token) return;
  await api.DELETE('/v1/devices/{expo_push_token}', { params: { path: { expo_push_token: token } } });
  await AsyncStorage.removeItem(TOKEN_KEY);
}
