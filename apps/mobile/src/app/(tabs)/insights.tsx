import { StyleSheet, View } from 'react-native';

import { ApiError } from '@/api/client';
import { useInsights, useRefreshInsights } from '@/api/queries';
import type { ArmStat } from '@/api/types';
import {
  Button,
  Card,
  EmptyState,
  ErrorState,
  Loading,
  ProgressBar,
  Row,
  Screen,
  SectionHeader,
  Text,
} from '@/components/ui';
import { armLabel, DIMENSION_LABELS, percent, TIME_WINDOW_LABELS } from '@/lib/format';
import { spacing } from '@/theme';

const DIMENSION_ORDER = ['time_window', 'nudge_type', 'tone', 'framing', 'length'];

export default function InsightsScreen() {
  const insights = useInsights();
  const refresh = useRefreshInsights();

  const refreshError =
    refresh.error instanceof ApiError && refresh.error.status === 429
      ? 'Brian reflected recently. Try again in an hour.'
      : refresh.error
        ? refresh.error.message
        : null;

  if (insights.isPending) return <Loading />;
  if (insights.isError) {
    return (
      <Screen>
        <ErrorState error={insights.error} onRetry={() => void insights.refetch()} />
      </Screen>
    );
  }

  const { stats, playbook } = insights.data;
  return (
    <Screen refreshing={insights.isRefetching} onRefresh={() => void insights.refetch()}>
      <Text variant="hero">Insights</Text>
      <Text muted>What Brian has learned from how you respond to nudges (last {stats.window_days} days).</Text>

      <View style={styles.tiles}>
        <Tile label="Nudges sent" value={String(stats.nudges_sent)} />
        <Tile label="Engaged" value={percent(stats.engagement_rate)} />
        <Tile label="Led to action" value={percent(stats.completion_rate)} />
        <Tile
          label="Typical reply time"
          value={
            stats.median_minutes_to_response === null ? '—' : `${Math.round(stats.median_minutes_to_response)} min`
          }
        />
      </View>
      {stats.best_time_window ? (
        <Card>
          <Text variant="caption" muted>
            Best time to reach you
          </Text>
          <Text variant="heading">{TIME_WINDOW_LABELS[stats.best_time_window] ?? stats.best_time_window}</Text>
        </Card>
      ) : null}

      <SectionHeader
        title="Brian's playbook for you"
        action={<Button title="Refresh" variant="ghost" small loading={refresh.isPending} onPress={() => refresh.mutate()} />}
      />
      {refreshError ? <Text muted>{refreshError}</Text> : null}
      {playbook ? (
        <Card>
          <Text>{playbook.summary}</Text>
          <List title="What works" items={playbook.what_works} />
          <List title="What to avoid" items={playbook.what_to_avoid} />
          <List title="Best times" items={playbook.best_times} />
          <List title="Trying next" items={playbook.experiments} />
          <Text variant="caption" muted>
            Updated {new Date(playbook.generated_at).toLocaleDateString()}
          </Text>
        </Card>
      ) : (
        <EmptyState
          title="No playbook yet"
          body="After you've reacted to a handful of nudges, Brian writes up what works for you."
        />
      )}

      <SectionHeader title="What the optimizer believes" />
      <Text variant="caption" muted>
        Each bar is the learned chance that this option gets a response from you. Brian mostly picks the strongest
        option and sometimes tries others to keep learning.
      </Text>
      {DIMENSION_ORDER.filter((d) => stats.by_dimension[d]).map((dimension) => (
        <Card key={dimension}>
          <Text variant="label">{DIMENSION_LABELS[dimension] ?? dimension}</Text>
          {(stats.by_dimension[dimension] ?? []).map((arm) => (
            <ArmBar key={arm.arm} dimension={dimension} arm={arm} />
          ))}
        </Card>
      ))}
    </Screen>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <Card style={styles.tile}>
      <Text variant="title">{value}</Text>
      <Text variant="caption" muted>
        {label}
      </Text>
    </Card>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <View style={styles.list}>
      <Text variant="label">{title}</Text>
      {items.map((item) => (
        <Text key={item} muted>
          • {item}
        </Text>
      ))}
    </View>
  );
}

function ArmBar({ dimension, arm }: { dimension: string; arm: ArmStat }) {
  return (
    <View style={styles.arm}>
      <Row style={styles.armHeader}>
        <Text variant="caption">{armLabel(dimension, arm.arm)}</Text>
        <Text variant="caption" muted>
          {Math.round(arm.learned_score * 100)}% · {arm.sent} sent
        </Text>
      </Row>
      <ProgressBar value={arm.learned_score} />
    </View>
  );
}

const styles = StyleSheet.create({
  tiles: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.md },
  tile: { flexGrow: 1, flexBasis: '45%', gap: 2 },
  list: { gap: 2, marginTop: spacing.sm },
  arm: { gap: 4, marginTop: spacing.xs },
  armHeader: { justifyContent: 'space-between' },
});
