import type { components } from './schema';

type Schemas = components['schemas'];

export type Profile = Schemas['ProfileOut'];
export type ProfileUpdate = Schemas['ProfileUpdate'];
export type Goal = Schemas['GoalOut'];
export type GoalDetail = Schemas['GoalDetail'];
export type GoalCreate = Schemas['GoalCreate'];
export type GoalUpdate = Schemas['GoalUpdate'];
export type GoalProgress = Schemas['GoalProgressOut'];
export type Milestone = Schemas['MilestoneOut'];
export type CheckIn = Schemas['CheckInOut'];
export type CheckInCreate = Schemas['CheckInCreate'];
export type Nudge = Schemas['NudgeOut'];
export type NudgeEvent = Schemas['NudgeEventIn'];
export type Insights = Schemas['InsightsOut'];
export type EngagementStats = Schemas['EngagementStats'];
export type ArmStat = Schemas['ArmStatOut'];
export type Playbook = Schemas['PlaybookOut'];
export type Conversation = Schemas['ConversationOut'];
export type ChatMessage = Schemas['ChatMessageOut'];
export type ChatRequest = Schemas['ChatRequest'];
export type ChatStreamEvent =
  | Schemas['ChatEventConversation']
  | Schemas['ChatEventText']
  | Schemas['ChatEventTool']
  | Schemas['ChatEventDone']
  | Schemas['ChatEventError'];

export type GoalCategory = GoalCreate['category'] & string;
export type GoalCadence = GoalCreate['cadence'] & string;
export type NudgeIntensity = Profile['nudge_intensity'];
