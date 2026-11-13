import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { DarkTheme, DefaultTheme, Stack, ThemeProvider } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { StyleSheet, View } from 'react-native';

import { ApiError } from '@/api/client';
import { useProfile } from '@/api/queries';
import { Button, ErrorState } from '@/components/ui';
import { AuthProvider, useAuth } from '@/lib/auth';
import { useNotificationObserver } from '@/notifications/useNotificationObserver';
import { darkColors, lightColors, spacing, useTheme } from '@/theme';

void SplashScreen.preventAutoHideAsync();

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error) =>
        !(error instanceof ApiError && error.status >= 400 && error.status < 500) && failureCount < 2,
    },
  },
});

export default function RootLayout() {
  const { dark } = useTheme();
  const base = dark ? DarkTheme : DefaultTheme;
  const colors = dark ? darkColors : lightColors;
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <ThemeProvider
          value={{
            ...base,
            colors: {
              ...base.colors,
              primary: colors.primary,
              background: colors.background,
              card: colors.surface,
              text: colors.text,
              border: colors.border,
            },
          }}>
          <StatusBar style="auto" />
          <RootNavigator />
        </ThemeProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

function RootNavigator() {
  const { session, initializing, signOut } = useAuth();
  const { colors } = useTheme();
  const signedIn = !!session;
  const profile = useProfile(signedIn);
  const onboarded = !!profile.data?.onboarded_at;
  const ready = !initializing && (!signedIn || !profile.isPending);

  useNotificationObserver(signedIn && onboarded);

  useEffect(() => {
    if (ready) void SplashScreen.hideAsync();
  }, [ready]);

  if (!ready) return null;

  if (signedIn && profile.isError) {
    return (
      <View style={[styles.errorScreen, { backgroundColor: colors.background }]}>
        <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />
        <Button title="Sign out" variant="ghost" onPress={() => void signOut()} />
      </View>
    );
  }

  return (
    <Stack screenOptions={{ headerShown: false }}>
      <Stack.Protected guard={!signedIn}>
        <Stack.Screen name="sign-in" />
      </Stack.Protected>
      <Stack.Protected guard={signedIn && !onboarded}>
        <Stack.Screen name="onboarding" />
      </Stack.Protected>
      <Stack.Protected guard={signedIn && onboarded}>
        <Stack.Screen name="(tabs)" />
        <Stack.Screen
          name="goal/new"
          options={{ presentation: 'modal', headerShown: true, title: 'New goal' }}
        />
        <Stack.Screen name="goal/[id]" options={{ headerShown: true, title: 'Goal', headerBackTitle: 'Back' }} />
        <Stack.Screen name="nudge/[id]" options={{ headerShown: true, title: 'Nudge', headerBackTitle: 'Back' }} />
      </Stack.Protected>
    </Stack>
  );
}

const styles = StyleSheet.create({
  errorScreen: { flex: 1, justifyContent: 'center', padding: spacing.xl, gap: spacing.md },
});
