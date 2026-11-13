import { useQueryClient } from '@tanstack/react-query';
import { useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import {
  ActivityIndicator,
  FlatList,
  KeyboardAvoidingView,
  Platform,
  Pressable,
  StyleSheet,
  TextInput,
  View,
} from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { fetchConversationMessages, keys, useConversations } from '@/api/queries';
import { Button, Row, Text } from '@/components/ui';
import { streamChat } from '@/lib/chat';
import { radius, spacing, useTheme } from '@/theme';

type ToolChip = { name: string; label: string; status: 'started' | 'finished' | 'failed' };
type UiMessage = {
  key: string;
  role: 'user' | 'assistant';
  text: string;
  tools: ToolChip[];
  pending?: boolean;
  error?: string;
};

const STARTERS = [
  'Help me set a new goal',
  'I did my workout today',
  'Nudge me less in the mornings',
  'What have you learned about me?',
];

export default function CoachScreen() {
  const { colors } = useTheme();
  const queryClient = useQueryClient();
  const params = useLocalSearchParams<{ nudgeId?: string; prefill?: string }>();
  const conversations = useConversations();

  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [nudgeId, setNudgeId] = useState<string | null>(null);
  const [input, setInput] = useState('');
  const [streaming, setStreaming] = useState(false);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const listRef = useRef<FlatList<UiMessage>>(null);
  const abortRef = useRef<AbortController | null>(null);

  // Replying to a nudge starts a fresh conversation about it.
  useEffect(() => {
    if (params.nudgeId) {
      abortRef.current?.abort();
      setMessages([]);
      setConversationId(null);
      setNudgeId(params.nudgeId);
      setInput(params.prefill ?? '');
      setHistoryLoaded(true);
    }
  }, [params.nudgeId, params.prefill]);

  // Otherwise resume the most recent conversation.
  useEffect(() => {
    if (historyLoaded || !conversations.data) return;
    const latest = conversations.data[0];
    setHistoryLoaded(true);
    if (!latest) return;
    setLoadingHistory(true);
    fetchConversationMessages(latest.id)
      .then((rows) => {
        setConversationId(latest.id);
        setMessages(rows.map((m) => ({ key: `h-${m.id}`, role: m.role, text: m.text, tools: [] })));
      })
      .catch(() => undefined)
      .finally(() => setLoadingHistory(false));
  }, [conversations.data, historyLoaded]);

  useEffect(() => () => abortRef.current?.abort(), []);

  function updateAssistant(key: string, update: (message: UiMessage) => UiMessage) {
    setMessages((current) => current.map((m) => (m.key === key ? update(m) : m)));
  }

  async function send(textOverride?: string) {
    const text = (textOverride ?? input).trim();
    if (!text || streaming) return;
    setInput('');
    const stamp = Date.now();
    const assistantKey = `a-${stamp}`;
    setMessages((current) => [
      ...current,
      { key: `u-${stamp}`, role: 'user', text, tools: [] },
      { key: assistantKey, role: 'assistant', text: '', tools: [], pending: true },
    ]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      for await (const event of streamChat(
        { message: text, conversation_id: conversationId, nudge_id: conversationId ? null : nudgeId },
        controller.signal,
      )) {
        switch (event.type) {
          case 'conversation':
            setConversationId(event.conversation_id);
            break;
          case 'text':
            updateAssistant(assistantKey, (m) => ({ ...m, text: m.text + event.delta }));
            break;
          case 'tool':
            updateAssistant(assistantKey, (m) => {
              const others = m.tools.filter((t) => t.name !== event.name || t.status !== 'started');
              return { ...m, tools: [...others, { name: event.name, label: event.label, status: event.status }] };
            });
            break;
          case 'error':
            updateAssistant(assistantKey, (m) => ({ ...m, error: event.message }));
            break;
          case 'done':
            break;
        }
      }
    } catch (error) {
      if (!controller.signal.aborted) {
        const message = error instanceof Error ? error.message : 'Could not reach Brian.';
        updateAssistant(assistantKey, (m) => ({ ...m, error: message }));
      }
    } finally {
      updateAssistant(assistantKey, (m) => ({ ...m, pending: false }));
      setStreaming(false);
      setNudgeId(null);
      // Brian's tools may have created goals, logged check-ins or changed settings.
      void queryClient.invalidateQueries({ queryKey: ['goals'] });
      void queryClient.invalidateQueries({ queryKey: keys.me });
      void queryClient.invalidateQueries({ queryKey: keys.conversations });
    }
  }

  function newChat() {
    abortRef.current?.abort();
    setMessages([]);
    setConversationId(null);
    setNudgeId(null);
    setInput('');
  }

  return (
    <SafeAreaView edges={['top']} style={[styles.flex, { backgroundColor: colors.background }]}>
      <KeyboardAvoidingView
        style={styles.flex}
        behavior={Platform.OS === 'ios' ? 'padding' : undefined}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 8 : 0}>
        <Row style={[styles.header, { borderBottomColor: colors.border }]}>
          <Text variant="title">Coach</Text>
          <Button title="New chat" variant="ghost" small onPress={newChat} disabled={streaming} />
        </Row>

        {loadingHistory ? (
          <View style={styles.center}>
            <ActivityIndicator color={colors.primary} />
          </View>
        ) : messages.length === 0 ? (
          <View style={styles.empty}>
            <Text variant="heading">{nudgeId ? 'Talk about this nudge' : 'What are we working on?'}</Text>
            <Text muted style={styles.emptyText}>
              Tell Brian about a goal, report progress, or change how you get nudged.
            </Text>
            {!nudgeId &&
              STARTERS.map((starter) => (
                <Pressable
                  key={starter}
                  onPress={() => void send(starter)}
                  style={[styles.starter, { borderColor: colors.border, backgroundColor: colors.surface }]}>
                  <Text>{starter}</Text>
                </Pressable>
              ))}
          </View>
        ) : (
          <FlatList
            ref={listRef}
            data={messages}
            keyExtractor={(m) => m.key}
            contentContainerStyle={styles.list}
            onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: true })}
            renderItem={({ item }) => <Bubble message={item} />}
          />
        )}

        <Row style={[styles.composer, { borderTopColor: colors.border, backgroundColor: colors.surface }]}>
          <TextInput
            value={input}
            onChangeText={setInput}
            placeholder="Message Brian"
            placeholderTextColor={colors.textMuted}
            multiline
            maxLength={4000}
            style={[styles.input, { color: colors.text, backgroundColor: colors.surfaceAlt }]}
          />
          <Button
            title="Send"
            small
            onPress={() => void send()}
            disabled={!input.trim() || streaming}
            loading={streaming}
          />
        </Row>
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
}

function Bubble({ message }: { message: UiMessage }) {
  const { colors } = useTheme();
  const mine = message.role === 'user';
  const thinking = message.pending && !message.text && message.tools.length === 0;
  return (
    <View style={[styles.bubbleRow, mine ? styles.right : styles.left]}>
      <View
        style={[
          styles.bubble,
          mine
            ? { backgroundColor: colors.userBubble }
            : { backgroundColor: colors.assistantBubble, borderColor: colors.border, borderWidth: StyleSheet.hairlineWidth },
        ]}>
        {message.tools.length > 0 ? (
          <View style={styles.tools}>
            {message.tools.map((tool) => (
              <Text key={`${tool.name}-${tool.status}`} variant="caption" muted>
                {tool.status === 'started' ? '⏳' : tool.status === 'finished' ? '✓' : '⚠︎'} {tool.label}
              </Text>
            ))}
          </View>
        ) : null}
        {thinking ? (
          <Text muted>Brian is thinking…</Text>
        ) : message.text ? (
          <Text color={mine ? colors.userBubbleText : colors.text} selectable>
            {message.text}
          </Text>
        ) : null}
        {message.error ? (
          <Text variant="caption" color={colors.danger}>
            {message.error}
          </Text>
        ) : null}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1 },
  header: {
    justifyContent: 'space-between',
    paddingHorizontal: spacing.lg,
    paddingVertical: spacing.sm,
    borderBottomWidth: StyleSheet.hairlineWidth,
  },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  empty: { flex: 1, padding: spacing.xl, gap: spacing.md, justifyContent: 'center' },
  emptyText: { marginBottom: spacing.sm },
  starter: { borderWidth: 1, borderRadius: radius.md, padding: spacing.md },
  list: { padding: spacing.lg, gap: spacing.md },
  bubbleRow: { flexDirection: 'row' },
  left: { justifyContent: 'flex-start' },
  right: { justifyContent: 'flex-end' },
  bubble: { maxWidth: '85%', borderRadius: radius.lg, paddingHorizontal: spacing.md, paddingVertical: spacing.sm, gap: spacing.xs },
  tools: { gap: 2 },
  composer: {
    alignItems: 'flex-end',
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    borderTopWidth: StyleSheet.hairlineWidth,
  },
  input: {
    flex: 1,
    minHeight: 40,
    maxHeight: 140,
    borderRadius: radius.md,
    paddingHorizontal: spacing.md,
    paddingVertical: spacing.sm,
    fontSize: 16,
  },
});
