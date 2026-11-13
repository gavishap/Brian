import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Alert, Linking, StyleSheet } from 'react-native';

import { useDeleteAccount, useProfile, useUpdateProfile } from '@/api/queries';
import type { NudgeIntensity, ProfileUpdate } from '@/api/types';
import { Button, Card, Chips, ErrorState, Loading, Row, Screen, SectionHeader, Text, TextField, TimeStepper } from '@/components/ui';
import { useAuth } from '@/lib/auth';
import { hhmm } from '@/lib/format';
import { notificationPermission, registerPushToken } from '@/notifications/register';
import { spacing } from '@/theme';

const INTENSITIES: readonly NudgeIntensity[] = ['gentle', 'balanced', 'intense'];
const PAUSES = [
  { label: '1 day', days: 1 },
  { label: '3 days', days: 3 },
  { label: '1 week', days: 7 },
];

export default function SettingsScreen() {
  const profile = useProfile();
  const update = useUpdateProfile();
  const deleteAccount = useDeleteAccount();
  const { session, signOut } = useAuth();
  const [name, setName] = useState<string | null>(null);
  const [permission, setPermission] = useState<string>('unknown');

  useFocusEffect(
    useCallback(() => {
      void notificationPermission().then(setPermission);
    }, []),
  );

  if (profile.isPending) return <Loading />;
  if (profile.isError) {
    return (
      <Screen>
        <ErrorState error={profile.error} onRetry={() => void profile.refetch()} />
      </Screen>
    );
  }
  const p = profile.data;
  const paused = p.nudges_paused_until && new Date(p.nudges_paused_until) > new Date();

  function save(body: ProfileUpdate) {
    update.mutate(body, { onError: (error) => Alert.alert('Could not save', error.message) });
  }

  async function enablePush() {
    if (permission === 'denied') {
      await Linking.openSettings();
      return;
    }
    const result = await registerPushToken({ prompt: true }).catch(() => null);
    setPermission(await notificationPermission());
    if (result && result.status !== 'registered') {
      Alert.alert('Notifications', `Push notifications are unavailable (${result.status}).`);
    }
  }

  function confirmDelete() {
    Alert.alert(
      'Delete your account?',
      'This permanently deletes your goals, check-ins, nudges and conversations. It cannot be undone.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: () =>
            deleteAccount.mutate(undefined, {
              onSuccess: () => void signOut(),
              onError: (error) => Alert.alert('Could not delete the account', error.message),
            }),
        },
      ],
    );
  }

  return (
    <Screen>
      <Text variant="hero">Settings</Text>

      <SectionHeader title="Profile" />
      <Card>
        <TextField
          label="Name"
          value={name ?? p.display_name ?? ''}
          onChangeText={setName}
          onEndEditing={() => name !== null && save({ display_name: name.trim() || null })}
          placeholder="Your first name"
        />
        <Text variant="caption" muted>
          {session?.user.email} · {p.timezone}
        </Text>
      </Card>

      <SectionHeader title="Nudges" />
      <Card>
        <Text variant="label">Intensity</Text>
        <Chips
          options={INTENSITIES}
          value={p.nudge_intensity}
          onChange={(value) => save({ nudge_intensity: value })}
          labels={{ gentle: 'Gentle', balanced: 'Balanced', intense: 'Intense' }}
        />
        <Text variant="label" style={styles.spaced}>
          Quiet hours
        </Text>
        <Row style={styles.wrap}>
          <TimeStepper value={hhmm(p.quiet_hours_start)} onChange={(v) => save({ quiet_hours_start: `${v}:00` })} />
          <Text muted>to</Text>
          <TimeStepper value={hhmm(p.quiet_hours_end)} onChange={(v) => save({ quiet_hours_end: `${v}:00` })} />
        </Row>
        <Text variant="label" style={styles.spaced}>
          {paused ? `Paused until ${new Date(p.nudges_paused_until as string).toLocaleString()}` : 'Pause nudges'}
        </Text>
        <Row style={styles.wrap}>
          {paused ? (
            <Button title="Resume now" small variant="secondary" onPress={() => save({ nudges_paused_until: null })} />
          ) : (
            PAUSES.map(({ label, days }) => (
              <Button
                key={label}
                title={label}
                small
                variant="secondary"
                onPress={() => save({ nudges_paused_until: new Date(Date.now() + days * 86_400_000).toISOString() })}
              />
            ))
          )}
        </Row>
      </Card>

      <SectionHeader title="Notifications" />
      <Card>
        <Text>
          {permission === 'granted'
            ? 'Notifications are on for this device.'
            : permission === 'denied'
              ? 'Notifications are blocked in system settings.'
              : 'Notifications are not set up on this device yet.'}
        </Text>
        {permission !== 'granted' ? (
          <Button
            title={permission === 'denied' ? 'Open system settings' : 'Turn on notifications'}
            small
            onPress={() => void enablePush()}
          />
        ) : null}
      </Card>

      <SectionHeader title="Account" />
      <Button title="Sign out" variant="secondary" onPress={() => void signOut()} />
      <Button title="Delete account" variant="danger" loading={deleteAccount.isPending} onPress={confirmDelete} />
    </Screen>
  );
}

const styles = StyleSheet.create({
  spaced: { marginTop: spacing.md },
  wrap: { flexWrap: 'wrap' },
});
