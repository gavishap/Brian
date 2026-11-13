import { router, Stack, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Alert, Pressable, StyleSheet, View } from 'react-native';

import { useAddMilestone, useArchiveGoal, useCheckIn, useGoal, useToggleMilestone, useUpdateGoal } from '@/api/queries';
import type { CheckIn } from '@/api/types';
import {
  Badge,
  Button,
  Card,
  ErrorState,
  Loading,
  ProgressBar,
  Row,
  Screen,
  SectionHeader,
  Text,
  TextField,
} from '@/components/ui';
import { cadenceLabel, humanize, relativeTime } from '@/lib/format';
import { spacing, useTheme } from '@/theme';

const KIND_LABELS: Record<CheckIn['kind'], string> = {
  done: 'Done',
  progress: 'Progress',
  skipped: 'Skipped',
  note: 'Note',
};

export default function GoalDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { colors } = useTheme();
  const goal = useGoal(id);
  const checkIn = useCheckIn();
  const update = useUpdateGoal(id);
  const archive = useArchiveGoal();
  const addMilestone = useAddMilestone(id);
  const toggleMilestone = useToggleMilestone(id);
  const [note, setNote] = useState('');
  const [milestone, setMilestone] = useState('');

  if (goal.isPending) return <Loading />;
  if (goal.isError) {
    return (
      <Screen edges={[]}>
        <ErrorState error={goal.error} onRetry={() => void goal.refetch()} />
      </Screen>
    );
  }
  const g = goal.data;
  const p = g.progress;

  function log(kind: CheckIn['kind']) {
    checkIn.mutate(
      { goalId: g.id, kind, note: note.trim() || null },
      {
        onSuccess: () => setNote(''),
        onError: (error) => Alert.alert('Could not log that', error.message),
      },
    );
  }

  function confirmArchive() {
    Alert.alert('Archive this goal?', 'Brian will stop nudging you about it. History is kept.', [
      { text: 'Cancel', style: 'cancel' },
      {
        text: 'Archive',
        style: 'destructive',
        onPress: () => archive.mutate(g.id, { onSuccess: () => router.back() }),
      },
    ]);
  }

  return (
    <Screen edges={[]} refreshing={goal.isRefetching} onRefresh={() => void goal.refetch()}>
      <Stack.Screen options={{ title: g.title }} />
      <View style={styles.header}>
        <Text variant="title">{g.title}</Text>
        <Row style={styles.wrap}>
          <Badge label={humanize(g.category)} />
          <Badge label={cadenceLabel(g)} />
          {g.status !== 'active' ? <Badge label={humanize(g.status)} tone="bad" /> : null}
        </Row>
        {g.why ? <Text muted>“{g.why}”</Text> : null}
      </View>

      <Card>
        <Row style={styles.between}>
          <Text variant="label">
            {p.period_count}/{p.period_target} {p.period_label}
          </Text>
          <Text variant="caption" muted>
            Streak {p.current_streak} · best {p.best_streak}
          </Text>
        </Row>
        <ProgressBar value={p.period_count / Math.max(1, p.period_target)} />
        <TextField value={note} onChangeText={setNote} placeholder="Add a note (optional)" />
        <Row style={styles.wrap}>
          <Button title="Done ✅" small onPress={() => log('done')} loading={checkIn.isPending} />
          <Button title="Some progress" small variant="secondary" onPress={() => log('progress')} />
          <Button title="Skipped" small variant="secondary" onPress={() => log('skipped')} />
          {note.trim() ? <Button title="Just a note" small variant="ghost" onPress={() => log('note')} /> : null}
        </Row>
      </Card>

      <SectionHeader title="Milestones" />
      <Card>
        {g.milestones.length === 0 ? <Text muted>Break the goal into steps you can tick off.</Text> : null}
        {g.milestones.map((m) => (
          <Pressable
            key={m.id}
            accessibilityRole="checkbox"
            accessibilityState={{ checked: !!m.completed_at }}
            onPress={() => toggleMilestone.mutate({ milestoneId: m.id, completed: !m.completed_at })}
            style={styles.milestone}>
            <Text>{m.completed_at ? '☑︎' : '☐'}</Text>
            <Text style={[styles.flex, m.completed_at ? { color: colors.textMuted, textDecorationLine: 'line-through' } : null]}>
              {m.title}
            </Text>
            {m.due_date ? (
              <Text variant="caption" muted>
                {m.due_date}
              </Text>
            ) : null}
          </Pressable>
        ))}
        <Row>
          <View style={styles.flex}>
            <TextField value={milestone} onChangeText={setMilestone} placeholder="New milestone" />
          </View>
          <Button
            title="Add"
            small
            variant="secondary"
            disabled={!milestone.trim()}
            loading={addMilestone.isPending}
            onPress={() => addMilestone.mutate({ title: milestone.trim() }, { onSuccess: () => setMilestone('') })}
          />
        </Row>
      </Card>

      <SectionHeader title="Recent check-ins" />
      <Card>
        {g.recent_check_ins.length === 0 ? <Text muted>No check-ins yet.</Text> : null}
        {g.recent_check_ins.map((c) => (
          <View key={c.id} style={styles.checkIn}>
            <Row style={styles.between}>
              <Text variant="label">{KIND_LABELS[c.kind]}</Text>
              <Text variant="caption" muted>
                {relativeTime(c.occurred_at)}
                {c.source !== 'app' ? ` · via ${c.source}` : ''}
              </Text>
            </Row>
            {c.note ? <Text muted>{c.note}</Text> : null}
          </View>
        ))}
      </Card>

      <SectionHeader title="Manage" />
      <Row style={styles.wrap}>
        {g.status === 'active' ? (
          <Button title="Pause" small variant="secondary" onPress={() => update.mutate({ status: 'paused' })} />
        ) : (
          <Button title="Resume" small variant="secondary" onPress={() => update.mutate({ status: 'active' })} />
        )}
        <Button title="Mark achieved 🎉" small variant="secondary" onPress={() => update.mutate({ status: 'completed' })} />
        <Button title="Archive" small variant="danger" onPress={confirmArchive} />
      </Row>
    </Screen>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  header: { gap: spacing.sm },
  wrap: { flexWrap: 'wrap' },
  between: { justifyContent: 'space-between' },
  milestone: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm, paddingVertical: spacing.xs },
  checkIn: { gap: 2, paddingVertical: spacing.xs },
});
