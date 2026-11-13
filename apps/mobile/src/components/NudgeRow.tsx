import { Link } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import type { Nudge } from '@/api/types';
import { relativeTime } from '@/lib/format';
import { spacing } from '@/theme';

import { Badge, Card, Text } from './ui';

const OUTCOME_LABELS: Record<string, { label: string; tone: 'good' | 'bad' | 'neutral' | 'primary' }> = {
  completed: { label: 'Done', tone: 'good' },
  replied: { label: 'Replied', tone: 'good' },
  opened: { label: 'Opened', tone: 'primary' },
  snoozed: { label: 'Snoozed', tone: 'neutral' },
  dismissed: { label: 'Dismissed', tone: 'bad' },
  ignored: { label: 'Missed', tone: 'neutral' },
  negative_feedback: { label: 'Less of these', tone: 'bad' },
};

export function NudgeRow({ nudge }: { nudge: Nudge }) {
  const outcome = nudge.outcome ? OUTCOME_LABELS[nudge.outcome] : undefined;
  return (
    <Link href={{ pathname: '/nudge/[id]', params: { id: nudge.id } }} asChild>
      <Pressable accessibilityRole="button">
        <Card style={styles.card}>
          <View style={styles.body}>
            <Text variant="label" numberOfLines={1}>
              {nudge.title ?? 'Brian'}
            </Text>
            <Text muted numberOfLines={2}>
              {nudge.body}
            </Text>
            <Text variant="caption" muted>
              {relativeTime(nudge.sent_at ?? nudge.scheduled_for)}
              {nudge.goal_title ? ` · ${nudge.goal_title}` : ''}
            </Text>
          </View>
          {outcome ? <Badge label={outcome.label} tone={outcome.tone} /> : null}
        </Card>
      </Pressable>
    </Link>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row', alignItems: 'flex-start', gap: spacing.md },
  body: { flex: 1, gap: 2 },
});
