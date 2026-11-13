import type { Goal } from '@/api/types';

export const TIME_WINDOW_LABELS: Record<string, string> = {
  early_morning: 'Early morning (6–8am)',
  morning: 'Morning (8–11am)',
  midday: 'Midday (11am–2pm)',
  afternoon: 'Afternoon (2–5pm)',
  evening: 'Evening (5–8pm)',
  night: 'Night (8–10pm)',
};

export const DIMENSION_LABELS: Record<string, string> = {
  time_window: 'Timing',
  nudge_type: 'Type of nudge',
  tone: 'Tone',
  framing: 'Framing',
  length: 'Length',
};

export function humanize(value: string): string {
  const text = value.replace(/_/g, ' ');
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function armLabel(dimension: string, arm: string): string {
  if (dimension === 'time_window') return TIME_WINDOW_LABELS[arm] ?? humanize(arm);
  return humanize(arm);
}

export function percent(value: number | null | undefined): string {
  return value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`;
}

export function cadenceLabel(goal: Pick<Goal, 'cadence' | 'target_per_period'>): string {
  const n = goal.target_per_period;
  switch (goal.cadence) {
    case 'weekly':
    case 'flexible':
      return `${n}× per week`;
    case 'weekdays':
      return n === 1 ? 'Every weekday' : `${n}× every weekday`;
    default:
      return n === 1 ? 'Every day' : `${n}× per day`;
  }
}

export function relativeTime(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return 'never';
  const diff = now - new Date(iso).getTime();
  const minutes = Math.round(diff / 60000);
  if (Math.abs(minutes) < 1) return 'just now';
  if (minutes < 0) {
    const ahead = -minutes;
    if (ahead < 60) return `in ${ahead} min`;
    if (ahead < 60 * 24) return `in ${Math.round(ahead / 60)} h`;
    return `in ${Math.round(ahead / 1440)} d`;
  }
  if (minutes < 60) return `${minutes} min ago`;
  if (minutes < 60 * 24) return `${Math.round(minutes / 60)} h ago`;
  return `${Math.round(minutes / 1440)} d ago`;
}

export function shortTime(iso: string): string {
  return new Date(iso).toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' });
}

/** "HH:MM:SS" from the API -> "HH:MM". */
export function hhmm(time: string): string {
  return time.slice(0, 5);
}

export function greeting(date = new Date()): string {
  const hour = date.getHours();
  if (hour < 5) return 'Up late';
  if (hour < 12) return 'Good morning';
  if (hour < 18) return 'Good afternoon';
  return 'Good evening';
}
