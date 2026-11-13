import { router, useLocalSearchParams } from 'expo-router';
import { Alert, StyleSheet, View } from 'react-native';

import { useCheckIn, useNudge } from '@/api/queries';
import { Badge, Button, Card, ErrorState, Loading, Screen, Text } from '@/components/ui';
import { humanize, shortTime } from '@/lib/format';
import { spacing, useTheme } from '@/theme';

// Shown after the person reacted from the notification itself (the event is already recorded).
const ACTION_MESSAGES: Record<string, string> = {
  done: 'Logged. Nice work! ✅',
  snooze: "Got it. Brian will remind you again in about an hour.",
  not_helpful: "Thanks. Brian will send fewer nudges like this one.",
  reply: 'Brian got your reply.',
};

export default function NudgeScreen() {
  const { id, action, reply } = useLocalSearchParams<{ id: string; action?: string; reply?: string }>();
  const { colors } = useTheme();
  const nudge = useNudge(id);
  const checkIn = useCheckIn();

  if (nudge.isPending) return <Loading />;
  if (nudge.isError) {
    return (
      <Screen edges={[]}>
        <ErrorState error={nudge.error} onRetry={() => void nudge.refetch()} />
      </Screen>
    );
  }
  const n = nudge.data;
  const alreadyDone = action === 'done' || n.outcome === 'completed';

  function markDone() {
    if (!n.goal_id) return;
    checkIn.mutate(
      { goalId: n.goal_id, kind: 'done', nudge_id: n.id },
      {
        onSuccess: () => void nudge.refetch(),
        onError: (error) => Alert.alert('Could not log that', error.message),
      },
    );
  }

  function talkToBrian() {
    router.navigate({ pathname: '/coach', params: { nudgeId: n.id, ...(reply ? { prefill: reply } : {}) } });
  }

  return (
    <Screen edges={[]}>
      {action && ACTION_MESSAGES[action] ? (
        <Card style={{ borderColor: colors.success }}>
          <Text variant="label">{ACTION_MESSAGES[action]}</Text>
          {reply ? <Text muted>“{reply}”</Text> : null}
        </Card>
      ) : null}

      <Card>
        <Text variant="caption" muted>
          {shortTime(n.sent_at ?? n.scheduled_for)}
          {n.goal_title ? ` · ${n.goal_title}` : ''}
        </Text>
        <Text variant="title">{n.title ?? 'Brian'}</Text>
        <Text>{n.body}</Text>
        {n.outcome ? (
          <View style={styles.badges}>
            <Badge label={humanize(n.outcome)} tone={n.outcome === 'completed' || n.outcome === 'replied' ? 'good' : 'neutral'} />
          </View>
        ) : null}
      </Card>

      {n.goal_id && !alreadyDone ? (
        <Button title="I did it ✅" onPress={markDone} loading={checkIn.isPending} />
      ) : null}
      <Button title="Talk to Brian about this" variant="secondary" onPress={talkToBrian} />
      {n.goal_id ? (
        <Button
          title="Open goal"
          variant="ghost"
          onPress={() => router.push({ pathname: '/goal/[id]', params: { id: n.goal_id as string } })}
        />
      ) : null}
    </Screen>
  );
}

const styles = StyleSheet.create({
  badges: { flexDirection: 'row', gap: spacing.sm, marginTop: spacing.xs },
});
