import { router } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet } from 'react-native';

import { useCreateGoal } from '@/api/queries';
import type { GoalCadence, GoalCategory } from '@/api/types';
import { Button, Chips, Row, Screen, Stepper, Text, TextField } from '@/components/ui';
import { humanize } from '@/lib/format';
import { spacing } from '@/theme';

const CATEGORIES: readonly GoalCategory[] = [
  'fitness',
  'health',
  'learning',
  'career',
  'finance',
  'relationships',
  'mindfulness',
  'creativity',
  'other',
];
const CADENCES: readonly GoalCadence[] = ['daily', 'weekdays', 'weekly', 'flexible'];
const PRIORITIES = ['1', '2', '3'] as const;

export default function NewGoalScreen() {
  const create = useCreateGoal();
  const [title, setTitle] = useState('');
  const [why, setWhy] = useState('');
  const [category, setCategory] = useState<GoalCategory>('other');
  const [cadence, setCadence] = useState<GoalCadence>('daily');
  const [perPeriod, setPerPeriod] = useState(1);
  const [priority, setPriority] = useState<(typeof PRIORITIES)[number]>('2');
  const weekly = cadence === 'weekly' || cadence === 'flexible';

  function submit() {
    create.mutate(
      {
        title: title.trim(),
        why: why.trim() || null,
        category,
        cadence,
        target_per_period: perPeriod,
        priority: Number(priority),
      },
      { onSuccess: (goal) => router.replace({ pathname: '/goal/[id]', params: { id: goal.id } }) },
    );
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen edges={[]}>
        <TextField label="Goal" value={title} onChangeText={setTitle} placeholder="e.g. Read 20 pages" maxLength={200} />
        <TextField
          label="Why it matters"
          value={why}
          onChangeText={setWhy}
          placeholder="Your own reason, in your words"
          multiline
        />
        <Text variant="label">Area</Text>
        <Chips
          options={CATEGORIES}
          value={category}
          onChange={setCategory}
          labels={Object.fromEntries(CATEGORIES.map((c) => [c, humanize(c)]))}
        />
        <Text variant="label">Rhythm</Text>
        <Chips
          options={CADENCES}
          value={cadence}
          onChange={(value) => {
            setCadence(value);
            setPerPeriod(value === 'weekly' || value === 'flexible' ? 3 : 1);
          }}
          labels={{ daily: 'Daily', weekdays: 'Weekdays', weekly: 'Per week', flexible: 'Flexible' }}
        />
        <Row>
          <Stepper value={perPeriod} onChange={setPerPeriod} min={1} max={14} />
          <Text muted>{weekly ? 'times a week' : 'times a day'}</Text>
        </Row>
        <Text variant="label">Priority</Text>
        <Chips options={PRIORITIES} value={priority} onChange={setPriority} labels={{ '1': 'High', '2': 'Normal', '3': 'Low' }} />
        {create.error ? <Text muted>{create.error.message}</Text> : null}
        <Button title="Create goal" onPress={submit} disabled={!title.trim()} loading={create.isPending} />
      </Screen>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, gap: spacing.md },
});
