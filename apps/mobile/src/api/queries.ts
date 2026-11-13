import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api, unwrap } from './client';
import type {
  CheckInCreate,
  GoalCreate,
  GoalUpdate,
  Profile,
  ProfileUpdate,
} from './types';

export const keys = {
  me: ['me'] as const,
  goals: (filter: 'current' | 'active' | 'all') => ['goals', filter] as const,
  goal: (id: string) => ['goal', id] as const,
  nudges: ['nudges'] as const,
  nudge: (id: string) => ['nudge', id] as const,
  insights: ['insights'] as const,
  conversations: ['conversations'] as const,
  messages: (conversationId: string) => ['messages', conversationId] as const,
};

// --- Profile --------------------------------------------------------------------------------

export function useProfile(enabled = true) {
  return useQuery({
    queryKey: keys.me,
    queryFn: async () => unwrap(await api.GET('/v1/me')),
    enabled,
  });
}

export function useUpdateProfile() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: ProfileUpdate) => unwrap(await api.PATCH('/v1/me', { body })),
    onSuccess: (profile: Profile) => queryClient.setQueryData(keys.me, profile),
  });
}

export function useDeleteAccount() {
  return useMutation({
    mutationFn: async () => unwrap(await api.DELETE('/v1/me')),
  });
}

// --- Goals ----------------------------------------------------------------------------------

export function useGoals(filter: 'current' | 'active' | 'all' = 'current') {
  return useQuery({
    queryKey: keys.goals(filter),
    queryFn: async () => unwrap(await api.GET('/v1/goals', { params: { query: { filter } } })),
  });
}

export function useGoal(id: string) {
  return useQuery({
    queryKey: keys.goal(id),
    queryFn: async () => unwrap(await api.GET('/v1/goals/{goal_id}', { params: { path: { goal_id: id } } })),
    enabled: !!id,
  });
}

function useInvalidateGoals() {
  const queryClient = useQueryClient();
  return (goalId?: string) => {
    void queryClient.invalidateQueries({ queryKey: ['goals'] });
    if (goalId) void queryClient.invalidateQueries({ queryKey: keys.goal(goalId) });
  };
}

export function useCreateGoal() {
  const invalidate = useInvalidateGoals();
  return useMutation({
    mutationFn: async (body: GoalCreate) => unwrap(await api.POST('/v1/goals', { body })),
    onSuccess: () => invalidate(),
  });
}

export function useUpdateGoal(goalId: string) {
  const invalidate = useInvalidateGoals();
  return useMutation({
    mutationFn: async (body: GoalUpdate) =>
      unwrap(await api.PATCH('/v1/goals/{goal_id}', { params: { path: { goal_id: goalId } }, body })),
    onSuccess: () => invalidate(goalId),
  });
}

export function useArchiveGoal() {
  const invalidate = useInvalidateGoals();
  return useMutation({
    mutationFn: async (goalId: string) =>
      unwrap(await api.DELETE('/v1/goals/{goal_id}', { params: { path: { goal_id: goalId }, query: { hard: false } } })),
    onSuccess: (_data, goalId) => invalidate(goalId),
  });
}

export function useCheckIn() {
  const queryClient = useQueryClient();
  const invalidate = useInvalidateGoals();
  return useMutation({
    mutationFn: async ({ goalId, ...body }: CheckInCreate & { goalId: string }) =>
      unwrap(await api.POST('/v1/goals/{goal_id}/check-ins', { params: { path: { goal_id: goalId } }, body })),
    onSuccess: (_data, variables) => {
      invalidate(variables.goalId);
      void queryClient.invalidateQueries({ queryKey: keys.nudges });
      void queryClient.invalidateQueries({ queryKey: keys.insights });
    },
  });
}

export function useAddMilestone(goalId: string) {
  const invalidate = useInvalidateGoals();
  return useMutation({
    mutationFn: async (body: { title: string; due_date?: string | null }) =>
      unwrap(await api.POST('/v1/goals/{goal_id}/milestones', { params: { path: { goal_id: goalId } }, body })),
    onSuccess: () => invalidate(goalId),
  });
}

export function useToggleMilestone(goalId: string) {
  const invalidate = useInvalidateGoals();
  return useMutation({
    mutationFn: async ({ milestoneId, completed }: { milestoneId: string; completed: boolean }) =>
      unwrap(
        await api.PATCH('/v1/goals/{goal_id}/milestones/{milestone_id}', {
          params: { path: { goal_id: goalId, milestone_id: milestoneId } },
          body: { completed },
        }),
      ),
    onSuccess: () => invalidate(goalId),
  });
}

// --- Nudges ---------------------------------------------------------------------------------

export function useNudges(limit = 30) {
  return useQuery({
    queryKey: [...keys.nudges, limit],
    queryFn: async () => unwrap(await api.GET('/v1/nudges', { params: { query: { limit } } })),
  });
}

export function useNudge(id: string) {
  return useQuery({
    queryKey: keys.nudge(id),
    queryFn: async () => unwrap(await api.GET('/v1/nudges/{nudge_id}', { params: { path: { nudge_id: id } } })),
    enabled: !!id,
  });
}

// --- Insights -------------------------------------------------------------------------------

export function useInsights() {
  return useQuery({
    queryKey: keys.insights,
    queryFn: async () => unwrap(await api.GET('/v1/insights')),
  });
}

export function useRefreshInsights() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => unwrap(await api.POST('/v1/insights/refresh')),
    onSuccess: (insights) => queryClient.setQueryData(keys.insights, insights),
  });
}

// --- Chat -----------------------------------------------------------------------------------

export function useConversations() {
  return useQuery({
    queryKey: keys.conversations,
    queryFn: async () => unwrap(await api.GET('/v1/conversations', { params: { query: { limit: 20 } } })),
  });
}

export async function fetchConversationMessages(conversationId: string) {
  return unwrap(
    await api.GET('/v1/conversations/{conversation_id}/messages', {
      params: { path: { conversation_id: conversationId } },
    }),
  );
}
