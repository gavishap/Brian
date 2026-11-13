import { useColorScheme } from 'react-native';

const palette = {
  indigo: '#4F46E5',
  indigoSoft: '#E0E7FF',
  indigoDark: '#A5B4FC',
  green: '#16A34A',
  amber: '#D97706',
  red: '#DC2626',
};

export const lightColors = {
  background: '#F7F7FB',
  surface: '#FFFFFF',
  surfaceAlt: '#EEF0F6',
  border: '#E2E4EC',
  text: '#11131A',
  textMuted: '#5E6372',
  primary: palette.indigo,
  primaryText: '#FFFFFF',
  primarySoft: palette.indigoSoft,
  success: palette.green,
  warning: palette.amber,
  danger: palette.red,
  userBubble: palette.indigo,
  userBubbleText: '#FFFFFF',
  assistantBubble: '#FFFFFF',
};

export type ThemeColors = typeof lightColors;

export const darkColors: ThemeColors = {
  background: '#0B0C10',
  surface: '#16181F',
  surfaceAlt: '#1F222B',
  border: '#2A2E39',
  text: '#F3F4F8',
  textMuted: '#A0A5B4',
  primary: '#6366F1',
  primaryText: '#FFFFFF',
  primarySoft: '#272A4A',
  success: '#22C55E',
  warning: '#F59E0B',
  danger: '#F87171',
  userBubble: '#6366F1',
  userBubbleText: '#FFFFFF',
  assistantBubble: '#1F222B',
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 8, md: 12, lg: 18, pill: 999 } as const;
export const font = {
  caption: 13,
  body: 16,
  label: 15,
  title: 22,
  hero: 30,
} as const;

export function useTheme() {
  const scheme = useColorScheme();
  const dark = scheme === 'dark';
  return { dark, colors: dark ? darkColors : lightColors, spacing, radius, font };
}

export type Theme = ReturnType<typeof useTheme>;
