import { Link } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import type { Goal } from '@/api/types';
import { cadenceLabel } from '@/lib/format';
import { spacing, useTheme } from '@/theme';

import { Button, Card, ProgressBar, Row, Text } from './ui';

export function GoalCard({
  goal,
  onCheckIn,
  checkingIn,
}: {
  goal: Goal;
  onCheckIn?: (goal: Goal) => void;
  checkingIn?: boolean;
}) {
  const { colors } = useTheme();
  const p = goal.progress;
  const complete = p.period_count >= p.period_target;
  return (
    <Link href={{ pathname: '/goal/[id]', params: { id: goal.id } }} asChild>
      <Pressable accessibilityRole="button" accessibilityLabel={`Open goal ${goal.title}`}>
        <Card>
          <Row style={styles.header}>
            <View style={styles.titleBlock}>
              <Text variant="heading" numberOfLines={2}>
                {goal.title}
              </Text>
              <Text variant="caption" muted>
                {cadenceLabel(goal)}
                {goal.status === 'paused' ? ' · paused' : ''}
              </Text>
            </View>
            {p.current_streak > 0 ? (
              <Text variant="label" color={colors.warning} accessibilityLabel={`${p.current_streak} streak`}>
                🔥 {p.current_streak}
              </Text>
            ) : null}
          </Row>
          <ProgressBar value={p.period_count / Math.max(1, p.period_target)} color={complete ? colors.success : undefined} />
          <Row style={styles.footer}>
            <Text variant="caption" muted>
              {p.period_count}/{p.period_target} {p.period_label}
            </Text>
            {onCheckIn && goal.status === 'active' ? (
              <Button
                title={complete ? 'Log again' : 'Done ✅'}
                small
                variant={complete ? 'secondary' : 'primary'}
                loading={checkingIn}
                onPress={() => onCheckIn(goal)}
              />
            ) : null}
          </Row>
        </Card>
      </Pressable>
    </Link>
  );
}

const styles = StyleSheet.create({
  header: { alignItems: 'flex-start', justifyContent: 'space-between' },
  titleBlock: { flex: 1, gap: 2 },
  footer: { justifyContent: 'space-between', marginTop: spacing.xs },
});
