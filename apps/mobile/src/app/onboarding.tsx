import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, View } from 'react-native';

import { api, unwrap } from '@/api/client';
import { keys } from '@/api/queries';
import type { GoalCadence, GoalCategory, NudgeIntensity } from '@/api/types';
import { Button, Card, Chips, ProgressBar, Row, Screen, Stepper, Text, TextField, TimeStepper } from '@/components/ui';
import { humanize } from '@/lib/format';
import { deviceTimeZone, registerPushToken } from '@/notifications/register';
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
const CADENCES: readonly GoalCadence[] = ['daily', 'weekdays', 'weekly'];
const INTENSITIES: readonly NudgeIntensity[] = ['gentle', 'balanced', 'intense'];
const INTENSITY_HINT: Record<NudgeIntensity, string> = {
  gentle: 'About one nudge a day.',
  balanced: 'Up to two a day.',
  intense: 'Up to three a day.',
};

const STEPS = ['about', 'goal', 'nudges', 'notifications'] as const;
type Step = (typeof STEPS)[number];

export default function OnboardingScreen() {
  const queryClient = useQueryClient();
  const timezone = deviceTimeZone() ?? 'UTC';
  const [step, setStep] = useState<Step>('about');
  const [name, setName] = useState('');
  const [title, setTitle] = useState('');
  const [why, setWhy] = useState('');
  const [category, setCategory] = useState<GoalCategory>('fitness');
  const [cadence, setCadence] = useState<GoalCadence>('daily');
  const [perPeriod, setPerPeriod] = useState(1);
  const [intensity, setIntensity] = useState<NudgeIntensity>('balanced');
  const [quietStart, setQuietStart] = useState('22:00');
  const [quietEnd, setQuietEnd] = useState('07:30');
  const [notificationStatus, setNotificationStatus] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const index = STEPS.indexOf(step);
  const next = () => setStep(STEPS[Math.min(index + 1, STEPS.length - 1)]);
  const back = () => setStep(STEPS[Math.max(index - 1, 0)]);

  async function enableNotifications() {
    setBusy(true);
    try {
      const result = await registerPushToken({ prompt: true });
      setNotificationStatus(result.status);
    } catch {
      setNotificationStatus('error');
    } finally {
      setBusy(false);
    }
  }

  async function finish() {
    setBusy(true);
    setError(null);
    try {
      unwrap(
        await api.POST('/v1/goals', {
          body: {
            title: title.trim(),
            why: why.trim() || null,
            category,
            cadence,
            target_per_period: perPeriod,
          },
        }),
      );
      const profile = unwrap(
        await api.PATCH('/v1/me', {
          body: {
            display_name: name.trim() || null,
            timezone,
            nudge_intensity: intensity,
            quiet_hours_start: `${quietStart}:00`,
            quiet_hours_end: `${quietEnd}:00`,
            onboarded: true,
          },
        }),
      );
      // Updating the profile flips the root guard to the main tabs.
      queryClient.setQueryData(keys.me, profile);
      void queryClient.invalidateQueries({ queryKey: ['goals'] });
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong. Try again.');
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen>
        <ProgressBar value={(index + 1) / STEPS.length} />

        {step === 'about' && (
          <View style={styles.section}>
            <Text variant="title">Hi, I'm Brian.</Text>
            <Text muted>
              I help you make steady progress on long-term goals. I'll check in at good moments, learn what kind of
              nudges actually help you, and adjust over time.
            </Text>
            <TextField
              label="What should I call you?"
              value={name}
              onChangeText={setName}
              placeholder="Your first name"
              autoComplete="given-name"
              textContentType="givenName"
            />
            <Text variant="caption" muted>
              Time zone: {timezone}
            </Text>
            <Button title="Continue" onPress={next} />
          </View>
        )}

        {step === 'goal' && (
          <View style={styles.section}>
            <Text variant="title">Pick one goal to start</Text>
            <Text muted>Make it concrete. You can add more later, or shape it with me in the Coach tab.</Text>
            <TextField
              label="Goal"
              value={title}
              onChangeText={setTitle}
              placeholder="e.g. Run 3 times a week"
              maxLength={200}
            />
            <TextField
              label="Why does it matter to you?"
              value={why}
              onChangeText={setWhy}
              placeholder="e.g. I want the energy to keep up with my kids"
              hint="Nudges that remind you of your own reason work better."
              multiline
            />
            <Text variant="label">Area</Text>
            <Chips
              options={CATEGORIES}
              value={category}
              onChange={setCategory}
              labels={Object.fromEntries(CATEGORIES.map((c) => [c, humanize(c)]))}
            />
            <Text variant="label">How often</Text>
            <Chips
              options={CADENCES}
              value={cadence}
              onChange={(value) => {
                setCadence(value);
                setPerPeriod(value === 'weekly' ? 3 : 1);
              }}
              labels={{ daily: 'Daily', weekdays: 'Weekdays', weekly: 'Times per week' }}
            />
            {cadence === 'weekly' ? (
              <Row>
                <Stepper value={perPeriod} onChange={setPerPeriod} min={1} max={14} />
                <Text muted>times a week</Text>
              </Row>
            ) : null}
            <Row style={styles.nav}>
              <Button title="Back" variant="ghost" onPress={back} />
              <Button title="Continue" onPress={next} disabled={title.trim().length === 0} />
            </Row>
          </View>
        )}

        {step === 'nudges' && (
          <View style={styles.section}>
            <Text variant="title">How should I nudge you?</Text>
            <Text muted>I'll learn the best times and tone from how you respond. Set the limits here.</Text>
            <Text variant="label">Intensity</Text>
            <Chips
              options={INTENSITIES}
              value={intensity}
              onChange={setIntensity}
              labels={{ gentle: 'Gentle', balanced: 'Balanced', intense: 'Intense' }}
            />
            <Text variant="caption" muted>
              {INTENSITY_HINT[intensity]}
            </Text>
            <Card>
              <Text variant="label">Quiet hours</Text>
              <Text variant="caption" muted>
                No nudges between these times.
              </Text>
              <Row style={styles.quiet}>
                <TimeStepper value={quietStart} onChange={setQuietStart} />
                <Text muted>to</Text>
                <TimeStepper value={quietEnd} onChange={setQuietEnd} />
              </Row>
            </Card>
            <Row style={styles.nav}>
              <Button title="Back" variant="ghost" onPress={back} />
              <Button title="Continue" onPress={next} />
            </Row>
          </View>
        )}

        {step === 'notifications' && (
          <View style={styles.section}>
            <Text variant="title">Let me reach you</Text>
            <Text muted>
              Nudges arrive as notifications. You can answer right from them: tap Done when you've done it, Later if
              now is a bad time, or reply to tell me how it's going. Every response helps me pick better moments.
            </Text>
            {notificationStatus === 'registered' ? (
              <Text variant="label">Notifications are on. ✅</Text>
            ) : notificationStatus === 'denied' ? (
              <Text muted>Notifications are off. You can turn them on later in Settings.</Text>
            ) : notificationStatus === 'unsupported' ? (
              <Text muted>This device can't receive push notifications (simulator). Continue on a real phone.</Text>
            ) : notificationStatus === 'misconfigured' ? (
              <Text muted>Push isn't configured in this build (missing EAS project id).</Text>
            ) : notificationStatus === 'error' ? (
              <Text muted>Couldn't turn on notifications right now. You can retry from Settings.</Text>
            ) : (
              <Button title="Turn on notifications" onPress={enableNotifications} loading={busy} />
            )}
            {error ? <Text color="#DC2626">{error}</Text> : null}
            <Row style={styles.nav}>
              <Button title="Back" variant="ghost" onPress={back} />
              <Button
                title={notificationStatus ? "Let's go" : 'Skip for now'}
                variant={notificationStatus ? 'primary' : 'secondary'}
                onPress={finish}
                loading={busy && notificationStatus !== null}
              />
            </Row>
          </View>
        )}
      </Screen>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  section: { gap: spacing.md },
  nav: { justifyContent: 'space-between', marginTop: spacing.md },
  quiet: { marginTop: spacing.sm, flexWrap: 'wrap' },
});
