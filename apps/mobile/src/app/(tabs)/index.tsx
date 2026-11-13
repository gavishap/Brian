import { Link } from 'expo-router';
import { useState } from 'react';
import { Alert, StyleSheet, View } from 'react-native';

import { useCheckIn, useGoals, useNudges, useProfile } from '@/api/queries';
import type { Goal } from '@/api/types';
import { GoalCard } from '@/components/GoalCard';
import { NudgeRow } from '@/components/NudgeRow';
import { Button, EmptyState, ErrorState, Loading, Screen, SectionHeader, Text } from '@/components/ui';
import { greeting } from '@/lib/format';
import { spacing } from '@/theme';

export default function TodayScreen() {
  const profile = useProfile();
  const goals = useGoals('active');
  const nudges = useNudges(5);
  const checkIn = useCheckIn();
  const [pendingGoal, setPendingGoal] = useState<string | null>(null);

  const name = profile.data?.display_name?.split(' ')[0];
  const remaining = (goals.data ?? []).filter((g) => g.progress.period_count < g.progress.period_target).length;

  function onCheckIn(goal: Goal) {
    setPendingGoal(goal.id);
    checkIn.mutate(
      { goalId: goal.id, kind: 'done' },
      {
        onSettled: () => setPendingGoal(null),
        onError: (error) => Alert.alert('Could not log that', error.message),
      },
    );
  }

  return (
    <Screen
      refreshing={goals.isRefetching || nudges.isRefetching}
      onRefresh={() => {
        void goals.refetch();
        void nudges.refetch();
      }}>
      <View style={styles.header}>
        <Text variant="hero">
          {greeting()}
          {name ? `, ${name}` : ''}
        </Text>
        {goals.data && goals.data.length > 0 ? (
          <Text muted>
            {remaining === 0
              ? 'Everything is done for now. Nice.'
              : `${remaining} goal${remaining === 1 ? '' : 's'} still open for this period.`}
          </Text>
        ) : null}
      </View>

      <SectionHeader
        title="Your goals"
        action={
          <Link href="/goal/new" asChild>
            <Button title="+ New" variant="ghost" small />
          </Link>
        }
      />
      {goals.isPending ? (
        <Loading />
      ) : goals.isError ? (
        <ErrorState error={goals.error} onRetry={() => void goals.refetch()} />
      ) : goals.data.length === 0 ? (
        <EmptyState
          title="No active goals"
          body="Add one, or tell Brian in the Coach tab what you want to work toward."
          action={
            <Link href="/goal/new" asChild>
              <Button title="Add a goal" small />
            </Link>
          }
        />
      ) : (
        goals.data.map((goal) => (
          <GoalCard key={goal.id} goal={goal} onCheckIn={onCheckIn} checkingIn={pendingGoal === goal.id} />
        ))
      )}

      <SectionHeader title="Recent nudges" />
      {nudges.isPending ? (
        <Loading />
      ) : nudges.isError ? (
        <ErrorState error={nudges.error} onRetry={() => void nudges.refetch()} />
      ) : nudges.data.length === 0 ? (
        <Text muted>Brian will start checking in once you have an active goal and notifications are on.</Text>
      ) : (
        nudges.data.map((nudge) => <NudgeRow key={nudge.id} nudge={nudge} />)
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  header: { gap: spacing.xs, marginBottom: spacing.sm },
});
