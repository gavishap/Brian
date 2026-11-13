import type { ConfigContext, ExpoConfig } from 'expo/config';

// Placeholder identifiers: change both to a reverse-DNS name you own before the first store build.
const BUNDLE_ID = 'com.example.brian';

export default ({ config }: ConfigContext): ExpoConfig => ({
  ...config,
  name: 'Brian',
  slug: 'brian',
  version: '0.1.0',
  // Web is a development preview for UI work (`npx expo start --web`); notifications are native-only.
  platforms: ['ios', 'android', 'web'],
  orientation: 'portrait',
  icon: './assets/images/icon.png',
  scheme: 'brian',
  userInterfaceStyle: 'automatic',
  ios: {
    icon: './assets/expo.icon',
    bundleIdentifier: BUNDLE_ID,
    supportsTablet: false,
    infoPlist: {
      ITSAppUsesNonExemptEncryption: false,
    },
  },
  android: {
    package: BUNDLE_ID,
    adaptiveIcon: {
      backgroundColor: '#EEF0FF',
      foregroundImage: './assets/images/android-icon-foreground.png',
      backgroundImage: './assets/images/android-icon-background.png',
      monochromeImage: './assets/images/android-icon-monochrome.png',
    },
    predictiveBackGestureEnabled: false,
  },
  web: {
    output: 'single',
    favicon: './assets/images/icon.png',
  },
  plugins: [
    'expo-router',
    [
      'expo-splash-screen',
      {
        backgroundColor: '#4F46E5',
        image: './assets/images/splash-icon.png',
        imageWidth: 76,
      },
    ],
    [
      'expo-notifications',
      {
        color: '#4F46E5',
        // The API sends every nudge on this Android channel (created at app start).
        defaultChannel: 'nudges',
        // Lets the background task run for notifications received while the app is backgrounded.
        enableBackgroundRemoteNotifications: true,
      },
    ],
    'expo-localization',
  ],
  experiments: {
    typedRoutes: true,
    reactCompiler: true,
  },
  extra: {
    eas: {
      // `eas init` prints this id; push tokens are scoped to it.
      projectId: process.env.EAS_PROJECT_ID,
    },
  },
});
