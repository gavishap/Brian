import type { ReactNode } from 'react';
import {
  ActivityIndicator,
  Pressable,
  RefreshControl,
  ScrollView,
  StyleSheet,
  Text as RNText,
  TextInput,
  type TextInputProps,
  type TextProps,
  View,
  type ViewProps,
  type ViewStyle,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { font, radius, spacing, useTheme } from '@/theme';

// --- Text -----------------------------------------------------------------------------------

type TextVariant = 'hero' | 'title' | 'heading' | 'body' | 'label' | 'caption';

const textStyles = StyleSheet.create({
  hero: { fontSize: font.hero, fontWeight: '700', lineHeight: 36 },
  title: { fontSize: font.title, fontWeight: '700', lineHeight: 28 },
  heading: { fontSize: 17, fontWeight: '600', lineHeight: 22 },
  body: { fontSize: font.body, lineHeight: 22 },
  label: { fontSize: font.label, fontWeight: '600', lineHeight: 20 },
  caption: { fontSize: font.caption, lineHeight: 18 },
});

export function Text({
  variant = 'body',
  muted,
  color,
  style,
  ...rest
}: TextProps & { variant?: TextVariant; muted?: boolean; color?: string }) {
  const { colors } = useTheme();
  return (
    <RNText
      style={[textStyles[variant], { color: color ?? (muted ? colors.textMuted : colors.text) }, style]}
      {...rest}
    />
  );
}

// --- Layout ---------------------------------------------------------------------------------

export function Screen({
  children,
  scroll = true,
  refreshing,
  onRefresh,
  contentStyle,
  edges = ['top'],
}: {
  children: ReactNode;
  scroll?: boolean;
  refreshing?: boolean;
  onRefresh?: () => void;
  contentStyle?: ViewStyle;
  edges?: ('top' | 'bottom' | 'left' | 'right')[];
}) {
  const { colors } = useTheme();
  return (
    <SafeAreaView edges={edges} style={[styles.flex, { backgroundColor: colors.background }]}>
      {scroll ? (
        <ScrollView
          contentContainerStyle={[styles.screenContent, contentStyle]}
          keyboardShouldPersistTaps="handled"
          refreshControl={
            onRefresh ? <RefreshControl refreshing={!!refreshing} onRefresh={onRefresh} /> : undefined
          }>
          {children}
        </ScrollView>
      ) : (
        <View style={[styles.flex, contentStyle]}>{children}</View>
      )}
    </SafeAreaView>
  );
}

export function Card({ style, ...rest }: ViewProps) {
  const { colors } = useTheme();
  return (
    <View
      style={[styles.card, { backgroundColor: colors.surface, borderColor: colors.border }, style]}
      {...rest}
    />
  );
}

export function Row({ style, ...rest }: ViewProps) {
  return <View style={[styles.row, style]} {...rest} />;
}

export function SectionHeader({ title, action }: { title: string; action?: ReactNode }) {
  return (
    <Row style={styles.sectionHeader}>
      <Text variant="heading">{title}</Text>
      {action}
    </Row>
  );
}

// --- Controls -------------------------------------------------------------------------------

type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger';

export function Button({
  title,
  onPress,
  variant = 'primary',
  loading,
  disabled,
  small,
  style,
  accessibilityLabel,
}: {
  title: string;
  onPress?: () => void;
  variant?: ButtonVariant;
  loading?: boolean;
  disabled?: boolean;
  small?: boolean;
  style?: ViewStyle;
  accessibilityLabel?: string;
}) {
  const { colors } = useTheme();
  const palette: Record<ButtonVariant, { bg: string; fg: string; border: string }> = {
    primary: { bg: colors.primary, fg: colors.primaryText, border: colors.primary },
    secondary: { bg: colors.surface, fg: colors.text, border: colors.border },
    ghost: { bg: 'transparent', fg: colors.primary, border: 'transparent' },
    danger: { bg: 'transparent', fg: colors.danger, border: colors.danger },
  };
  const p = palette[variant];
  const inactive = disabled || loading;
  return (
    <Pressable
      accessibilityRole="button"
      accessibilityLabel={accessibilityLabel ?? title}
      accessibilityState={{ disabled: !!inactive, busy: !!loading }}
      disabled={inactive}
      onPress={onPress}
      style={({ pressed }) => [
        styles.button,
        small && styles.buttonSmall,
        { backgroundColor: p.bg, borderColor: p.border, opacity: inactive ? 0.55 : pressed ? 0.8 : 1 },
        style,
      ]}>
      {loading ? (
        <ActivityIndicator color={p.fg} />
      ) : (
        <Text variant="label" color={p.fg} style={small ? styles.buttonSmallText : undefined}>
          {title}
        </Text>
      )}
    </Pressable>
  );
}

export function TextField({
  label,
  hint,
  error,
  style,
  ...rest
}: TextInputProps & { label?: string; hint?: string; error?: string | null }) {
  const { colors } = useTheme();
  return (
    <View style={styles.field}>
      {label ? <Text variant="label">{label}</Text> : null}
      <TextInput
        placeholderTextColor={colors.textMuted}
        style={[
          styles.input,
          rest.multiline && styles.inputMultiline,
          { color: colors.text, backgroundColor: colors.surface, borderColor: error ? colors.danger : colors.border },
          style,
        ]}
        {...rest}
      />
      {error ? (
        <Text variant="caption" color={colors.danger}>
          {error}
        </Text>
      ) : hint ? (
        <Text variant="caption" muted>
          {hint}
        </Text>
      ) : null}
    </View>
  );
}

export function Chips<T extends string>({
  options,
  value,
  onChange,
  labels,
}: {
  options: readonly T[];
  value: T;
  onChange: (value: T) => void;
  labels?: Partial<Record<T, string>>;
}) {
  const { colors } = useTheme();
  return (
    <View style={styles.chips}>
      {options.map((option) => {
        const selected = option === value;
        return (
          <Pressable
            key={option}
            accessibilityRole="radio"
            accessibilityState={{ selected }}
            onPress={() => onChange(option)}
            style={[
              styles.chip,
              {
                backgroundColor: selected ? colors.primary : colors.surface,
                borderColor: selected ? colors.primary : colors.border,
              },
            ]}>
            <Text variant="caption" color={selected ? colors.primaryText : colors.text}>
              {labels?.[option] ?? option}
            </Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export function Stepper({
  value,
  onChange,
  min,
  max,
  format,
  step = 1,
}: {
  value: number;
  onChange: (value: number) => void;
  min: number;
  max: number;
  step?: number;
  format?: (value: number) => string;
}) {
  const { colors } = useTheme();
  return (
    <Row style={[styles.stepper, { borderColor: colors.border, backgroundColor: colors.surface }]}>
      <Pressable
        accessibilityLabel="Decrease"
        disabled={value - step < min}
        onPress={() => onChange(Math.max(min, value - step))}
        style={styles.stepperButton}>
        <Text variant="title" muted={value - step < min}>
          −
        </Text>
      </Pressable>
      <Text variant="label" style={styles.stepperValue}>
        {format ? format(value) : value}
      </Text>
      <Pressable
        accessibilityLabel="Increase"
        disabled={value + step > max}
        onPress={() => onChange(Math.min(max, value + step))}
        style={styles.stepperButton}>
        <Text variant="title" muted={value + step > max}>
          +
        </Text>
      </Pressable>
    </Row>
  );
}

/** "HH:MM" picker in 30-minute steps (no native picker dependency). */
export function TimeStepper({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const [h, m] = value.split(':').map(Number);
  const minutes = (h ?? 0) * 60 + (m ?? 0);
  const toLabel = (total: number) => {
    const hh = Math.floor(total / 60) % 24;
    const mm = total % 60;
    return `${String(hh).padStart(2, '0')}:${String(mm).padStart(2, '0')}`;
  };
  return (
    <Stepper
      value={minutes}
      min={0}
      max={23 * 60 + 30}
      step={30}
      format={toLabel}
      onChange={(next) => onChange(toLabel(next))}
    />
  );
}

export function ProgressBar({ value, color }: { value: number; color?: string }) {
  const { colors } = useTheme();
  const pct = Math.max(0, Math.min(1, value));
  return (
    <View style={[styles.track, { backgroundColor: colors.surfaceAlt }]}>
      <View style={[styles.fill, { width: `${pct * 100}%`, backgroundColor: color ?? colors.primary }]} />
    </View>
  );
}

export function Badge({ label, tone = 'neutral' }: { label: string; tone?: 'neutral' | 'good' | 'bad' | 'primary' }) {
  const { colors } = useTheme();
  const fg = { neutral: colors.textMuted, good: colors.success, bad: colors.danger, primary: colors.primary }[tone];
  return (
    <View style={[styles.badge, { borderColor: fg }]}>
      <Text variant="caption" color={fg}>
        {label}
      </Text>
    </View>
  );
}

// --- States ---------------------------------------------------------------------------------

export function Loading() {
  const { colors } = useTheme();
  return (
    <View style={styles.center}>
      <ActivityIndicator color={colors.primary} />
    </View>
  );
}

export function EmptyState({ title, body, action }: { title: string; body?: string; action?: ReactNode }) {
  return (
    <Card style={styles.empty}>
      <Text variant="heading">{title}</Text>
      {body ? (
        <Text muted style={styles.centerText}>
          {body}
        </Text>
      ) : null}
      {action}
    </Card>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : 'Something went wrong.';
  return (
    <EmptyState
      title="Couldn't load this"
      body={message}
      action={onRetry ? <Button title="Try again" variant="secondary" small onPress={onRetry} /> : undefined}
    />
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  screenContent: { padding: spacing.lg, gap: spacing.lg, paddingBottom: spacing.xxl * 2 },
  card: { borderRadius: radius.lg, borderWidth: StyleSheet.hairlineWidth, padding: spacing.lg, gap: spacing.sm },
  row: { flexDirection: 'row', alignItems: 'center', gap: spacing.sm },
  sectionHeader: { justifyContent: 'space-between', marginTop: spacing.sm },
  button: {
    minHeight: 48,
    borderRadius: radius.md,
    borderWidth: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingHorizontal: spacing.lg,
  },
  buttonSmall: { minHeight: 36, paddingHorizontal: spacing.md, borderRadius: radius.sm },
  buttonSmallText: { fontSize: 14 },
  field: { gap: spacing.xs },
  input: {
    minHeight: 48,
    borderRadius: radius.md,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: font.body,
  },
  inputMultiline: { minHeight: 96, textAlignVertical: 'top' },
  chips: { flexDirection: 'row', flexWrap: 'wrap', gap: spacing.sm },
  chip: {
    borderRadius: radius.pill,
    borderWidth: 1,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
  },
  stepper: {
    alignSelf: 'flex-start',
    borderWidth: 1,
    borderRadius: radius.md,
    paddingHorizontal: spacing.xs,
    gap: 0,
  },
  stepperButton: { paddingHorizontal: spacing.md, paddingVertical: spacing.xs },
  stepperValue: { minWidth: 64, textAlign: 'center' },
  track: { height: 8, borderRadius: radius.pill, overflow: 'hidden' },
  fill: { height: '100%', borderRadius: radius.pill },
  badge: { borderWidth: 1, borderRadius: radius.pill, paddingHorizontal: spacing.sm, paddingVertical: 2 },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: spacing.xl },
  empty: { alignItems: 'center', gap: spacing.md, paddingVertical: spacing.xl },
  centerText: { textAlign: 'center' },
});
