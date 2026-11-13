import { useState } from 'react';
import { KeyboardAvoidingView, Platform, StyleSheet, View } from 'react-native';

import { Button, Screen, Text, TextField } from '@/components/ui';
import { useAuth } from '@/lib/auth';
import { spacing, useTheme } from '@/theme';

export default function SignInScreen() {
  const { sendCode, verifyCode } = useAuth();
  const { colors } = useTheme();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const validEmail = /^\S+@\S+\.\S+$/.test(email.trim());

  async function onSendCode() {
    setBusy(true);
    setError(null);
    try {
      await sendCode(email);
      setStep('code');
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not send the code.');
    } finally {
      setBusy(false);
    }
  }

  async function onVerify() {
    setBusy(true);
    setError(null);
    try {
      await verifyCode(email, code);
      // The auth listener updates the session and the root layout routes onward.
    } catch (e) {
      setError(e instanceof Error ? e.message : 'That code did not work.');
      setBusy(false);
    }
  }

  return (
    <KeyboardAvoidingView style={styles.flex} behavior={Platform.OS === 'ios' ? 'padding' : undefined}>
      <Screen contentStyle={styles.content}>
        <View style={styles.hero}>
          <Text variant="hero">Brian</Text>
          <Text muted>Your coach for the goals that take longer than a week.</Text>
        </View>

        {step === 'email' ? (
          <View style={styles.form}>
            <TextField
              label="Email"
              value={email}
              onChangeText={setEmail}
              autoCapitalize="none"
              autoComplete="email"
              keyboardType="email-address"
              textContentType="emailAddress"
              placeholder="you@example.com"
              returnKeyType="send"
              onSubmitEditing={() => validEmail && void onSendCode()}
              error={error}
            />
            <Button title="Email me a code" onPress={onSendCode} disabled={!validEmail} loading={busy} />
          </View>
        ) : (
          <View style={styles.form}>
            <Text>
              We sent a 6-digit code to <Text variant="label">{email.trim()}</Text>.
            </Text>
            <TextField
              label="Code"
              value={code}
              onChangeText={(value) => setCode(value.replace(/\D/g, '').slice(0, 6))}
              keyboardType="number-pad"
              autoComplete="one-time-code"
              textContentType="oneTimeCode"
              placeholder="123456"
              maxLength={6}
              error={error}
            />
            <Button title="Sign in" onPress={onVerify} disabled={code.length !== 6} loading={busy} />
            <Button
              title="Use a different email"
              variant="ghost"
              onPress={() => {
                setStep('email');
                setCode('');
                setError(null);
              }}
            />
          </View>
        )}

        <Text variant="caption" color={colors.textMuted} style={styles.legal}>
          By continuing you agree to receive coaching notifications you can turn off at any time.
        </Text>
      </Screen>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  content: { flexGrow: 1, justifyContent: 'center', gap: spacing.xl },
  hero: { gap: spacing.sm },
  form: { gap: spacing.md },
  legal: { textAlign: 'center' },
});
