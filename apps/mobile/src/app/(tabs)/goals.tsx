import { Link } from 'expo-router';
import { useState } from 'react';

import { useGoals } from '@/api/queries';
import { GoalCard } from '@/components/GoalCard';
import { Button, Chips, EmptyState, ErrorState, Loading, Screen, SectionHeader, Text } from '@/components/ui';

const FILTERS = ['current', 'all'] as const;

export default function GoalsScreen() {
  const [filter, setFilter] = useState<(typeof FILTERS)[number]>('current');
  const goals = useGoals(filter);

  return (
    <Screen refreshing={goals.isRefetching} onRefresh={() => void goals.refetch()}>
      <Text variant="hero">Goals</Text>
      <Chips options={FILTERS} value={filter} onChange={setFilter} labels={{ current: 'Current', all: 'All' }} />
      <SectionHeader
        title={filter === 'current' ? 'Active and paused' : 'Everything'}
        action={
          <Link href="/goal/new" asChild>
            <Button title="+ New goal" variant="ghost" small />
          </Link>
        }
      />
      {goals.isPending ? (
        <Loading />
      ) : goals.isError ? (
        <ErrorState error={goals.error} onRetry={() => void goals.refetch()} />
      ) : goals.data.length === 0 ? (
        <EmptyState title="No goals yet" body="Long-term goals work best when they're specific and have a rhythm." />
      ) : (
        goals.data.map((goal) => <GoalCard key={goal.id} goal={goal} />)
      )}
    </Screen>
  );
}
